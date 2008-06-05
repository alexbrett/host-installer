# Copyright (c) 2005-2006 XenSource, Inc. All use and distribution of this 
# copyrighted material is governed by and subject to terms and conditions 
# as licensed by XenSource, Inc. All other rights reserved.
# Xen, XenSource and XenEnterprise are either registered trademarks or 
# trademarks of XenSource Inc. in the United States and/or other countries.

###
# XEN CLEAN INSTALLER
# Disk discovery and utilities
#
# written by Andrew Peace

import re
import os.path
import subprocess
import util
import popen2
import xelogging

# hd* -> (ide has majors 3, 22, 33, 34, 56, 57, 88, 89, 90, 91, each major has
# two disks, with minors 0... and 64...)
ide_majors = [ 3, 22, 33, 34, 56, 57, 88, 89, 90, 91 ]
disk_nodes  = [ (x, 0) for x in ide_majors ]
disk_nodes += [ (x, 64) for x in ide_majors ]

# sd* -> (sd-mod has majors 8, 65 ... 71: each device has eight minors, each 
# major has sixteen disks).
disk_nodes += [ (8, x * 16) for x in range(16) ]
disk_nodes += [ (65, x * 16) for x in range(16) ]
disk_nodes += [ (66, x * 16) for x in range(16) ]
disk_nodes += [ (67, x * 16) for x in range(16) ]
disk_nodes += [ (68, x * 16) for x in range(16) ]
disk_nodes += [ (69, x * 16) for x in range(16) ]
disk_nodes += [ (70, x * 16) for x in range(16) ]
disk_nodes += [ (71, x * 16) for x in range(16) ]

# /dev/cciss : c[0-7]d[0-15]: Compaq Next Generation Drive Array
# /dev/ida   : c[0-7]d[0-15]: Compaq Intelligent Drive Array
for major in range(72, 80) + range(104, 112):
    disk_nodes += [ (major, x * 16) for x in range(16) ]

# /dev/rd    : c[0-7]d[0-31]: Mylex DAC960 PCI RAID controller
for major in range(48, 56):
    disk_nodes += [ (major, x * 8) for x in range(32) ]

def getDiskList():
    # read the partition tables:
    parts = open("/proc/partitions")
    partlines = map(lambda x: re.sub(" +", " ", x).strip(),
                    parts.readlines())
    parts.close()

    # parse it:
    disks = []
    for l in partlines:
        try:
           (major, minor, size, name) = l.split(" ")
           (major, minor, size) = (int(major), int(minor), int(size))
           if (major, minor) in disk_nodes:
               disks.append(name.replace("!", "/"))
        except:
            # it wasn't an actual entry, maybe the headers or something:
            continue

    return disks

# this works on this principle that everything that isn't a
# disk (according to our disk_nodes) is a partition.
def getPartitionList():
    # read the partition tables:
    parts = open("/proc/partitions")
    partlines = map(lambda x: re.sub(" +", " ", x).strip(),
                    parts.readlines())
    parts.close()

    rv = []
    for l in partlines:
        try:
           (major, minor, size, name) = l.split(" ")
           (major, minor, size) = (int(major), int(minor), int(size))
           if (major, minor) not in disk_nodes:
               rv.append(name.replace("!", "/"))
        except:
            # it wasn't an actual entry, maybe the headers or something:
            continue

    return rv

def partitionsOnDisk(dev):
    if dev.startswith('/dev/'):
        dev = dev[5:]
    dev = dev.replace('/', '!')
    return filter(lambda x: x.startswith(dev),
                  os.listdir(os.path.join('/sys/block', dev)))

def getQualifiedDiskList():
    return map(lambda x: getQualifiedDeviceName(x), getDiskList())

def getQualifiedPartitionList():
    return [getQualifiedDeviceName(x) for x in getPartitionList()]

def getRemovableDeviceList():
    devs = os.listdir('/sys/block')
    removable_devs = []
    for d in devs:
        if isRemovable(d):
            removable_devs.append(d.replace("!", "/"))

    return removable_devs

def removable(device):
    if device.startswith('/dev/'):
        device = device[5:]
    return device in getRemovableDeviceList()

def getQualifiedDeviceName(disk):
    return "/dev/%s" % disk

# Given a partition (e.g. /dev/sda1), get a disk name:
def diskFromPartition(partition):
    numlen = 1
    while 1:
        try:
            partnum = int(partition[len(partition) - numlen:])
        except:
            # move back one as this value failed.
            numlen -= 1 
            break
        else:
            numlen += 1

    # is it a cciss?
    if True in [partition.startswith(x) for x in ['/dev/cciss', '/dev/ida', '/dev/rd']]:
        numlen += 1 # need to get rid of trailing 'p'

    # is it /dev/disk/by-id/XYZ-part<k>?
    if partition.startswith("/dev/disk/by-id"):
        return partition[:partition.rfind("-part")]

    return partition[:len(partition) - numlen]
        

def __readOneLineFile__(filename):
    try:
        f = open(filename)
        value = f.readline()
        f.close()
        return value
    except Exception, e:
        raise e

def getDiskDeviceVendor(dev):
    if dev.startswith("/dev/"):
        dev = re.match("/dev/(.*)", dev).group(1)
    dev = dev.replace("/", "!")
    if os.path.exists("/sys/block/%s/device/vendor" % dev):
        return __readOneLineFile__("/sys/block/%s/device/vendor" % dev).strip(' \n')
    else:
        return ""

def getDiskDeviceModel(dev):
    if dev.startswith("/dev/"):
        dev = re.match("/dev/(.*)", dev).group(1)
    dev = dev.replace("/", "!")
    if os.path.exists("/sys/block/%s/device/model" % dev):
        return __readOneLineFile__("/sys/block/%s/device/model" % dev).strip('  \n')
    else:
        return ""
    
def getDiskDeviceSize(dev):
    if dev.startswith("/dev/"):
        dev = re.match("/dev/(.*)", dev).group(1)
    dev = dev.replace("/", "!")
    if os.path.exists("/sys/block/%s/device/block/size" % dev):
        return int(__readOneLineFile__("/sys/block/%s/device/block/size" % dev))
    elif os.path.exists("/sys/block/%s/size" % dev):
        return int(__readOneLineFile__("/sys/block/%s/size" % dev))

def isRemovable(dev):
    if dev.startswith("/dev/"):
        dev = re.match("/dev/(.*)", dev).group(1)
    dev = dev.replace("/", "!")
    if os.path.exists("/sys/block/%s/removable" % dev):
        return int(__readOneLineFile__("/sys/block/%s/removable" % dev)) == 1
    else:
        return False

def blockSizeToGBSize(blocks):
    return (long(blocks) * 512) / (1024 * 1024 * 1024)
    
def getHumanDiskSize(blocks):
    return "%d GB" % blockSizeToGBSize(blocks)

def getExtendedDiskInfo(disk):
    devname = disk.replace("/dev/", "")

    return (getDiskDeviceVendor(devname),
            getDiskDeviceModel(devname),
            getDiskDeviceSize(devname))


################################################################################
# TOOLS FOR PARTITIONING DISKS

def clearDiskPartitions(disk):
    assert disk[:5] == '/dev/'
    assert util.runCmd2(["dd", "if=/dev/zero", "of=%s" % disk, "count=512", "bs=1"]) == 0

# partitions is a list of sizes in MB, currently we only make primary partitions.
# this is a completely destructive process.
#
# The last size may be -1, which is a special value indicating that the rest
# of the disk should be used.
def writePartitionTable(disk, partitions):
    xelogging.log("About to write partition table %s to disk %s" % (partitions, disk))
    
    clearDiskPartitions(disk)

    pipe = subprocess.Popen(['/sbin/fdisk', disk], stdin = subprocess.PIPE,
                            stdout = subprocess.PIPE, stderr = subprocess.PIPE)

    for i in range(0, len(partitions)):
        pipe.stdin.write('n\n') # new partition
        pipe.stdin.write('p\n') # primary
        pipe.stdin.write('%d\n' % (i + 1)) # ith partition
        pipe.stdin.write('\n')  # default start cylinder
        if partitions[i] == -1:
            pipe.stdin.write('\n') # use rest of disk
        else:
            pipe.stdin.write('+%dM\n' % partitions[i]) # size in MB

    # write the partition table to disk:
    pipe.stdin.write('w\n')

    # wait for fdisk to finish:
    assert pipe.wait() == 0

    # on older installer filesystem with udev=058 we needed to 
    # hackily call udevstart - do this if appropriate
    if os.path.exists('/sbin/udevstart'):
        os.system('/sbin/udevstart')

    # on newer installer fielsystems with udev=091 we can do the
    # correct thing, which is to wait for the udev events to be
    # correctly processed:
    if os.path.exists('/sbin/udevsettle'):
        os.system('/sbin/udevsettle --timeout=5')


def makeActivePartition(disk, partition_number):
    xelogging.log("About to make an active partition on disk %s" % disk)

    pipe = subprocess.Popen(['/sbin/fdisk', disk], stdin = subprocess.PIPE,
                            stdout = subprocess.PIPE, stderr = subprocess.PIPE)

    pipe.stdin.write('a\n') # new partition
    pipe.stdin.write('%d\n' % int(partition_number)) # ith partition

    # write the partition table to disk:
    pipe.stdin.write('w\n')

    # wait for fdisk to finish:
    assert pipe.wait() == 0

def getVolumeGroups():
    """ Returns a list of strings, each of which is the
    name of a volume group found by 'vgs'. """

    pipe = popen2.Popen3("vgs --noheadings 2>/dev/null")
    vgs = pipe.fromchild.readlines()
    pipe.wait()

    vgs = [ x.strip().split(" ")[0] for x in vgs ]

    return vgs
    
# get a mapping of partitions to the volume group they are part of:
def getVGPVMap():
    pipe = popen2.Popen3("pvscan 2>/dev/null | egrep '*[ \t]*PV' | awk '{print $2,$4;}'")
    volumes = pipe.fromchild.readlines()
    pipe.wait()

    volumes = map(lambda x: x.strip('\n').split(' '), volumes)
    rv = {}
    for [vg, pv] in volumes:
        if rv.has_key(pv):
            rv[pv].append(vg)
        else:
            rv[pv] = [vg]

    return rv

# given a list of disks, work out which ones are part of volume
# groups that will cause a problem if we install XE to those disks:
def findProblematicVGs(disks):
    # which partitions are the volue groups on?
    vgpvmap = getVGPVMap()

    # which disks are the volume groups on?
    vgdiskmap = {}
    for vg in vgpvmap:
        vgdiskmap[vg] = [diskFromPartition(x) for x in vgpvmap[vg]]

    # for each VG, map the disk list to a boolean list saying whether that
    # disk is in the set we're installing to:
    vgusedmap = {}
    for vg in vgdiskmap:
        vgusedmap[vg] = [disk in disks for disk in vgdiskmap[vg]]

    # now, a VG is problematic if it its vgusedmap entry contains a mixture
    # of Trua and False.  If it's entirely True or entirely False, that's OK:
    problems = []
    for vg in vgusedmap:
        p = False
        for x in vgusedmap[vg]:
            if x != vgusedmap[vg][0]:
                p = True
        if p:
            problems.append(vg)

    return problems

def determinePartitionName(guestdisk, partitionNumber):
    if guestdisk.find("cciss") != -1 or \
        guestdisk.find("ida") != -1 or \
        guestdisk.find("rd") != -1 or \
        guestdisk.find("sg") != -1 or \
        guestdisk.find("i2o") != -1 or \
        guestdisk.find("amiraid") != -1 or \
        guestdisk.find("iseries") != -1 or \
        guestdisk.find("emd") != -1 or \
        guestdisk.find("carmel") != -1:
        return guestdisk + "p%d" % partitionNumber
    elif "disk/by-id" in guestdisk:
        return guestdisk + "-part%d" % partitionNumber
    else:
        return guestdisk + "%d" % partitionNumber
