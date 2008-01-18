#!/usr/bin/python
# Copyright (c) 2005-2006 XenSource, Inc. All use and distribution of this 
# copyrighted material is governed by and subject to terms and conditions 
# as licensed by XenSource, Inc. All other rights reserved.
# Xen, XenSource and XenEnterprise are either registered trademarks or 
# trademarks of XenSource Inc. in the United States and/or other countries.

###
# P2V TOOL
# Text user interface functions
#
# written by Mark Nijmeijer
# updated by Andrew Peace

from snack import *
from version import *
import snackutil
import findroot
import re
import os
import sys
import p2v_constants
import p2v_backend
import time
import xelogging
import tui
import tui.network
import tui.progress
from p2v import closeClogs
import uicontroller
import xmlrpclib
import socket

from p2v_error import P2VMountError, P2VCliError

def requireNetworking(answers):
    return tui.network.requireNetworking(answers)

# welcome screen:
def welcome_screen(answers):
    button = ButtonChoiceWindow(tui.screen,
                       "Welcome to %s P2V" % PRODUCT_BRAND,
                       """This tool will copy a locally-installed operating system into a %s running on a %s.""" % (BRAND_GUEST_SHORT, BRAND_SERVER),
                       ['Ok', 'Cancel'], width=50)

    # advance to next screen:
    if button == "cancel": return uicontroller.EXIT
    return 1

# specify target
def get_target(answers):
    bb = ButtonBar(tui.screen, [('Ok', 'ok'), ('Back', 'back')])
    t = TextboxReflowed(40, "Which %s host would you like to save your %s to?" % (PRODUCT_BRAND, BRAND_GUEST))
    e_host = Entry(25)
    e_user = Entry(25)
    e_pw = Entry (25, password=1)

    entries = Grid(2, 3)
    entries.setField(Textbox(10, 1, "Host"), 0, 0)
    entries.setField(e_host, 1, 0)
    entries.setField(Textbox(10, 1, "User"), 0, 1)
    entries.setField(e_user, 1, 1)
    entries.setField(Textbox(10, 1, "Password"), 0, 2)
    entries.setField(e_pw, 1, 2)

    gf = GridFormHelp(tui.screen, 'Target Host', None, 1, 3)
    gf.add(t, 0, 0, padding = (0, 0, 0, 1))
    gf.add(entries, 0, 1, padding = (0, 0, 0, 1))
    gf.add(bb, 0, 2)

    result = gf.runOnce()
    if bb.buttonPressed(result) == 'back':
        return -1
    else:
        # CA-6614: validate input and clearer error reporting
        host = e_host.value()
        user = e_user.value()
        pw = e_pw.value()
        msg = ''
        
        if len(host) == 0:
            msg = 'Host'
        elif len(user) == 0:
            msg = 'User'
        elif len(pw) == 0:
            msg = 'Password'
        if len(msg) > 0:
            ButtonChoiceWindow(
                tui.screen, "Error", "%s field is blank.\n\nPlease enter a value for the field and try again." % msg,
                ['Back']
                )
            return 0

        # check we can connect to the server:
        if not host.startswith('https://') or not host.startswith('http://'):
            host = "https://" + host
        try:
            server = xmlrpclib.Server(host)
            rc = server.session.login_with_password(user, pw)
            if rc['Status'] == 'Success':
                answers['target-host-name'] = host
                answers['target-host-user'] = user
                answers['target-host-password'] = pw
                return 1
            else:
                # session login error
                msg = rc['ErrorDescription'][2]
        except socket.error, (e, str):
            # error connecting to server
            msg = str
        except IOError, e:
            msg = e
        except xmlrpclib.ProtocolError, e:
            msg = e.errmsg
        except Exception, e:
            msg = e

        ButtonChoiceWindow(
            tui.screen, "Error", "Unable to connect to server.  Please check the details and try again.\n\nThe error was '%s'." % msg,
            ['Back']
            )
        return 0

# select storage repository:
# TODO better error checking.
def select_sr(answers):
    # login
    server = xmlrpclib.Server(answers['target-host-name'])
    rc = server.session.login_with_password(answers['target-host-user'], answers['target-host-password'])
    assert rc['Status'] == 'Success', "Failure logging in to server that previously worked."
    session = rc['Value']

    # get a list of SRs
    rc = server.SR.get_all_records(session)
    if rc['Status'] == 'Failure' and rc['ErrorDescription'][0] == 'HOST_IS_SLAVE':
        # CA-9297: redirect to master
        server.session.logout(session)
        answers['target-host-name'] = answers['target-host-name'][:answers['target-host-name'].find('//')+2] + rc['ErrorDescription'][1]
        server = xmlrpclib.Server(answers['target-host-name'])
        rc = server.session.login_with_password(answers['target-host-user'], answers['target-host-password'])
        assert rc['Status'] == 'Success', "Failure logging in to pool master."
        session = rc['Value']
        rc = server.SR.get_all_records(session)

    assert rc['Status'] == 'Success', "Failure calling server.SR.get_all_records(%s)" % session

    srs = rc['Value']

    rc = server.SM.get_all_records(session)
    assert rc['Status'] == 'Success', "Failure calling server.SM.get_all_records(%s)" % session

    sms = rc['Value']

    list_srs = []
    for sr in srs.values():
        for sm in sms.values():
            if sr['type'] == sm['type'] and 'VDI_CREATE' in sm['capabilities']:
                if sr['name_label'] != "":
                    name = sr['name_label']
                else:
                    name = sr['uuid']
                item = (name, sr['uuid'])
                list_srs.append(item)
                break

    server.session.logout(session)
    rc, entry = ListboxChoiceWindow(
        tui.screen, "Storage repository", "Which storage repository would you like to create disk images in?",
        list_srs, ['Ok', 'Back'], width=70
        )

    if rc in [None, 'ok']:
        answers['target-sr'] = entry
        return 1
    else:
        return -1

#let the user chose the OS install
def os_install_screen(answers):
    os_install_strings = []
    supported_os_installs = []

    tui.progress.showMessageDialog("Working", "Scanning for installed operating systems, please wait...")
    os_installs = findroot.findroot()
    tui.progress.clearModelessDialog()

    for os in os_installs: 
        if findroot.isP2Vable(os):
            os_install_strings.append(os[p2v_constants.OS_NAME] + " " + os[p2v_constants.OS_VERSION] + "  (" + os[p2v_constants.DEV_NAME] + ")")
            supported_os_installs.append(os)
    
    if len(os_install_strings) > 0:
        (button, entry) = ListboxChoiceWindow(tui.screen,
                "Select OS",
                "Which OS installation do you want to P2V?",
                os_install_strings,
                ['Ok', 'Back'])
            
        if button == "ok" or button == None:
            xelogging.log("os_install = " + str(supported_os_installs[entry]))
            answers['osinstall'] = supported_os_installs[entry]
            return 1
        else:
            return -1
    else: 
        # TODO, CA-2747  pull this out of a supported OS list.
        xelogging.log("No supported operating systems found.")
        raise RuntimeError, "No supported operating systems found.  Please refer to the user guide for a list of supported operating systems and volume management technologies."

def size_screen(answers):
    tui.progress.showMessageDialog("Working", "Determining size of the selected operating system, please wait...")
    p2v_backend.determine_size(answers['osinstall'])
    tui.progress.clearModelessDialog()

    total_size = str(long(answers['osinstall'][p2v_constants.FS_TOTAL_SIZE]) / 1024**2)
    used_size = str(long(answers['osinstall'][p2v_constants.FS_USED_SIZE]) / 1024**2)
    success = False
    while not success:
        (button, size) = EntryWindow(tui.screen,
                "Enter Volume Size",
                """Please enter the size of the volume that will be created on the %s. 
                
Currently, %s MB is in use by the chosen operating system.  The default size of the volume is 150%% of the used size or 4096 MB, whichever is bigger.""" % (BRAND_SERVER, used_size),
                [('Size in MB:', total_size)],
                buttons = ['Ok', 'Back'])

        if long(size[0]) < long(used_size):
            ButtonChoiceWindow(tui.screen,
                "Size too small",
                "Minimum size = %s MB." % used_size,
                buttons = ['Ok'])
        else:
            new_size = long(size[0])
            success = True

    if button == "ok" or button == None:
        answers['target-vm-disksize-mb'] = new_size
        return 1
    else:
        return -1

def confirm_screen(answers):
    button = ButtonChoiceWindow(tui.screen, "Confirm Operation",
        "All required information has now been collected.  The data transfer may take a long time and cause significant network traffic.",
        ['Start Transfer', 'Back'], width = 40)

    if button in ['start transfer', None]:
        return 1
    else:
        return -1

def finish_screen():
    xelogging.writeLog("/tmp/install-log")
    xelogging.collectLogs('/tmp')
    ButtonChoiceWindow(tui.screen, "Finish P2V", """P2V operation successfully completed. Please press enter to reboot the machine.""", ['Ok'], width = 50)
    return 1

