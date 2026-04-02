#!/bin/bash
name="ims_pcu"
echo "USB Probing: $name"
while [ true ];
do
  rmmod $name 2>/dev/null
  sleep 2
  modprobe $name
  dmesg | tail -5
done
