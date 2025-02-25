#!/bin/bash

# Last Edit : 20250225-01
# For configuring RutilVM 4.5.5
# Based on CentOS Stream 9

stty erase ^H
export LANG=C

validate_ip() {
  local ip=$1
  if [[ $ip =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
    IFS='.' read -r -a octets <<< "$ip"
    for octet in "${octets[@]}"; do
      if ((octet > 255 || octet < 0)); then return 1; fi
    done
    return 0
  elif [[ $ip =~ ^([a-fA-F0-9]{1,4}:){1,7}([a-fA-F0-9]{1,4})?$ ]]; then
    return 0
  elif [[ $ip =~ ^([a-fA-F0-9]{1,4}:)*::([a-fA-F0-9]{1,4}:)*([a-fA-F0-9]{1,4})?$ ]]; then
    return 0
  fi
  return 1
}

task_host_add() {
	while true; do
		read -p "> Enter the number of hosts: " host_count
		if [[ "$host_count" =~ ^[1-9][0-9]*$ ]]; then
			break
		else
			echo "Invalid input. Please enter a number greater than 0."
		fi
	done
	
	for ((i=1; i<=host_count; i++)); do
		while true; do
			if [ $i -eq 1 ]; then
				read -p "> Enter the hostname of this host: " hostname
				hostnamectl set-hostname "$hostname"
			else
				read -p "> Enter the hostname of another host: " hostname
			fi
			if grep -q "\s$hostname" /etc/hosts; then
				echo "The hostname $hostname already exists in /etc/hosts."
				read -p "Do you want to overwrite it? (Yes, No): " overwrite
				if [[ $overwrite =~ ^[Yy]$ ]]; then
					sed -i "/\b$hostname\b/d" /etc/hosts
					break
				else
					echo "Skipping this hostname."
					continue 2
				fi
			else
				break
			fi
		done
		while true; do
			read -p "> Enter the IP address for $hostname: " ip
			if ! validate_ip "$ip"; then
				echo "Invalid IP address. Please try again."
				continue
			fi
			if grep -q "^$ip\s" /etc/hosts; then
				echo "The IP address $ip already exists in /etc/hosts."
				read -p "Do you want to overwrite it? (Yes, No): " overwrite
				if [[ "${overwrite,,}" =~ ^(y|yes)$ ]]; then
					sed -i "/^$ip\s/d" /etc/hosts
					break
				else
					echo "Skipping this IP address."
					continue 2
				fi
			else
				break
			fi
		done
		echo "$ip    $hostname" | tee -a /etc/hosts > /dev/null
	done
}

task_bonding() {
	echo "- Network bonding configuration"
	col1_width=8
	col2_width=5
	col3_width=18
	col4_width=8
	col5_width=8
	col6_width=29
	echo ==============================================================================================
	printf "| %-${col1_width}s | %-${col2_width}s | %-${col3_width}s | %-${col4_width}s | %-${col5_width}s | %-${col6_width}s|\n" "DEVICE" "STATE" "CONNECTION" "SPEED" "DUPLEX" "IP"
	echo +--------------------------------------------------------------------------------------------+
	device_name=`nmcli d | grep -Ev "lo|virbr" | tail -n +2 | awk '{print $1}'`
	for dev_name in $device_name; do
		interface=$dev_name
		state=$(ip -br a s $dev_name | grep -v lo | awk '{print $2}')
		connection=$(nmcli d | grep $dev_name | awk '{print $4}')
		speed=$(ethtool $dev_name | grep -i speed | awk '{print $2}' | awk '{ print substr($0, 1, length($0)-3) }')
		duplex=$(ethtool $dev_name | grep -i duplex | awk '{print $2}')
		ip4=$(ip -br a s $dev_name | grep -v lo | awk '{print $3}')
		printf "| %-${col1_width}s | %-${col2_width}s | %-${col3_width}s | %-${col4_width}s | %-${col5_width}s | %-${col6_width}s|\n" "$interface" "$state" "$connection" "$speed" "$duplex" "$ip4"
	done
	echo ==============================================================================================
	echo
	while true; do
		echo -n "> Bond First Device (ex: ens161): "
		read slave_first_device
		device_list=$(nmcli d | tail -n +2 | awk '{print $1}' | grep -Ev 'lo|virbr|bond')
		if [[ $device_list =~ (^|[[:space:]])$slave_first_device($|[[:space:]]) ]]; then
			break
		else
			echo "Invalid device. Please enter a valid device name."
			slave_first_device=""
		fi
	done
	while true; do
		echo -n "> Bond Second Device (ex: ens162): "
		read slave_second_device
		device_list=$(nmcli d | tail -n +2 | awk '{print $1}' | grep -Ev "lo|virbr|bond|$slave_first_device")
		if [[ $device_list =~ (^|[[:space:]])$slave_second_device($|[[:space:]]) ]]; then
			break
		else
			echo "Invalid device. Please enter a valid device name."
			slave_second_device=""
		fi
	done
	read -e -i "bond0" -p "> Bond Name [bond0]: " bond_name
	if nmcli con show "$bond_name" &> /dev/null; then
		nmcli con delete "$bond_name" >/dev/null 1>&1
	fi
	if nmcli con show bond-slave-"$slave_first_device" &> /dev/null; then
		nmcli con delete bond-slave-"$slave_first_device" >/dev/null 1>&1
	fi
	if nmcli con show bond-slave-"$slave_second_device" &> /dev/null; then
		nmcli con delete bond-slave-"$slave_second_device" >/dev/null 1>&1
	fi
	while true; do
		hostname_ip=$(grep $(hostname) /etc/hosts | grep -v localhost | awk '{print $1}' || true)
		if [[ -n "$hostname_ip" ]]; then
			read -e -i "$hostname_ip" -p "> $bond_name IP address [${hostname_ip}]: " bond_ip
			if [[ -z "$bond_ip" ]]; then
				bond_ip="$hostname_ip"
			fi
		else
			read -p "> $bond_name IP address: " bond_ip
		fi 
		if [[ -z "$bond_ip" ]]; then
			echo "Please enter an IP address."
		elif validate_ip "$bond_ip"; then
			break
		else
			echo "Please enter a valid IPv4 address with each octet between 0 and 255."
		fi
	done
	while true; do
		read -e -i "24" -p "> Prefix(Netmask): " network_prefix
		if [ -z "$network_prefix" ] ; then
			network_prefix="24"
			break
		elif [[ "$network_prefix" =~ ^[0-9]+$ ]] && [ "$network_prefix" -ge 1 ] && [ "$network_prefix" -le 32 ]; then
			break
		else
			echo "Netmask must be a number between 1 and 32. Please try again."
		fi
	done
	while true; do
	read -e -i "${bond_ip%.*}." -p "> Gateway : " network_gateway
	if [[ -z "$network_gateway" ]]; then
		echo "Please enter a gateway IP address."
	elif validate_ip "$network_gateway"; then
		break
	else
		echo "Please enter a valid IPv4 or IPv6 gateway address."
	fi
	done
	while true; do
		read -e -i "8.8.8.8" -p "> DNS: " network_dns1
		if [[ -z "$network_dns1" ]]; then
			network_dns1="8.8.8.8"
		fi
		if validate_ip "$bond_ip"; then
			break
		else
			echo "Please enter a valid IPv4 address with each octet between 0 and 255."
		fi
	done
	backup_dir="/etc/sysconfig/network-scripts/backup"
	if [ ! -d "$backup_dir" ]; then
		mkdir $backup_dir
	fi
	for ifcfg_org in /etc/sysconfig/network-scripts/ifcfg-e*; do
		mv $ifcfg_org $backup_dir >/dev/null 2>&1
	done
	nmcli c a type bond ifname $bond_name con-name $bond_name bond.options mode=1,miimon=100 >/dev/null 1>&1
	nmcli c a type ethernet ifname $slave_first_device master $bond_name >/dev/null 1>&1
	nmcli c a type ethernet ifname $slave_second_device master $bond_name >/dev/null 1>&1
	nmcli c m $bond_name ipv4.addresses $bond_ip/$network_prefix
	nmcli c m $bond_name ipv4.gateway $network_gateway
	nmcli c m $bond_name ipv4.dns $network_dns1
	nmcli c m $bond_name ipv4.dns-search ""
	nmcli c m $bond_name ipv4.method manual
	nmcli c m $bond_name primary $slave_first_device
	nmcli c m $bond_name downdelay 0
	nmcli c m $bond_name updelay 0
	nmcli c d $bond_name >/dev/null 2>&1 && nmcli c u $bond_name >/dev/null 2>&1
	nmcli c r >/dev/null 1>&1
	sleep 2
	echo
	echo "- Bonding configuration information"
	echo ==============================================================================================
	nmcli d | grep -Ev "lo|virbr" | head -n 1
	echo ==============================================================================================
	nmcli d | grep -Ev "lo|virbr" | tail -n +2
	echo ----------------------------------------------------------------------------------------------
	cat /proc/net/bonding/$bond_name | grep -Ev "Driver|Interval|Delay|addr|ID|Count" | tail -n +2
	ip4_address=$(nmcli c s $bond_name|grep IP4.ADDRESS | awk '{print $2}')
	ip4_gateway=$(nmcli c s $bond_name|grep IP4.GATEWAY | awk '{print $2}')
	ip4_dns=$(nmcli c s $bond_name|grep IP4.DNS|awk '{print $2}')
	bond_options=$(nmcli c s $bond_name|grep bond.options|awk '{print $2}'|head -n 1)
	echo ----------------------------------------------------------------------------------------------
	echo "IP Address  : "$ip4_address
	echo "Gateway     : "$ip4_gateway
	echo "DNS         : "$ip4_dns
	echo "Bond option : "$bond_options
	echo ----------------------------------------------------------------------------------------------
}

task_repository() {
	dnf clean all >/dev/null 1>&1
	if ! dnf list installed ovirt-engine-appliance &>/dev/null; then
		echo -n "Installing RutilVM engine package"
		dnf install -y ovirt-engine-appliance >/dev/null 2>&1 &
		dnf_pid=$!
		while kill -0 "$dnf_pid" 2>/dev/null; do
			echo -n "."
			sleep 1
		done
		echo -e "\nRutilVM engine package installation done."
	fi
}

function task_ntp() {
    local ntp_address default_ntp="203.248.240.140"
    local chrony_config="/etc/chrony.conf"
    if [ ! -f "${chrony_config}.org" ]; then
        cp "$chrony_config" "${chrony_config}.org"
        echo "Original chrony configuration backed up."
    fi
    while true; do
        read -e -i "$default_ntp" -p "> Enter the NTP server address (ex: $default_ntp): " ntp_address
        ntp_address=${ntp_address:-$default_ntp}
        if validate_ip "$ntp_address"; then
            echo "Valid NTP server address provided: $ntp_address"
            break
        else
            echo "Invalid IP address. Please enter a valid IPv4 address."
        fi
    done
    sed -i '/^server/d' "$chrony_config"
    echo "server $ntp_address iburst" >> "$chrony_config"
    echo "Chrony configuration updated with NTP server: $ntp_address"
    if systemctl is-active --quiet chronyd; then
        echo "Chrony daemon is already active. Restarting to apply changes..."
        systemctl restart chronyd >/dev/null 2>&1
    else
        echo "Starting chrony daemon..."
        systemctl enable chronyd >/dev/null 2>&1
        systemctl start chronyd >/dev/null 2>&1
    fi
    timedatectl set-ntp yes >/dev/null 2>&1
    timedatectl set-timezone Asia/Seoul >/dev/null 2>&1
    chronyc -a makestep >/dev/null 2>&1
    echo "NTP synchronization and timezone configured successfully."
}

task_lun_scan() {
    if [ -d "/sys/class/fc_host" ]; then
        host_device=$(ls -l /sys/class/fc_host | grep -v total | awk 'NF > 0 {print $9}')
        if [ -n "$host_device" ]; then
            for host_number in $host_device; do
                echo "Rescanning host /sys/class/scsi_host/$host_number"
                echo "- - -" > /sys/class/scsi_host/$host_number/scan
            done
        fi
    fi
    if rpm -q sg3_utils > /dev/null; then
        rescan-scsi-bus.sh > /dev/null
        rescan-scsi-bus.sh -r | tail -n 3
    fi
}

task_answers.conf() {
	cat << ANSWERS.CONF_EOF > /etc/ovirt-hosted-engine/answers.conf.setup
[environment:default]
OVEHOSTED_CORE/HE_OFFLINE_DEPLOYMENT=bool:True
OVEHOSTED_CORE/deployProceed=bool:True
OVEHOSTED_CORE/enableKeycloak=bool:False
OVEHOSTED_CORE/forceIpProceed=none:None
OVEHOSTED_CORE/screenProceed=bool:True
OVEHOSTED_ENGINE/clusterName=str:Default
OVEHOSTED_ENGINE/datacenterName=str:Default
OVEHOSTED_ENGINE/enableHcGlusterService=none:None
OVEHOSTED_ENGINE/insecureSSL=none:None
OVEHOSTED_ENGINE/adminPassword=str:admin!123
OVEHOSTED_NETWORK/bridgeName=str:ovirtmgmt
OVEHOSTED_NETWORK/network_test=str:ping
OVEHOSTED_NETWORK/network_test_tcp_address=none:None
OVEHOSTED_NETWORK/network_test_tcp_port=none:None
OVEHOSTED_NOTIF/destEmail=str:root@localhost
OVEHOSTED_NOTIF/smtpPort=str:25
OVEHOSTED_NOTIF/smtpServer=str:localhost
OVEHOSTED_NOTIF/sourceEmail=str:root@localhost
OVEHOSTED_STORAGE/discardSupport=bool:False
OVEHOSTED_STORAGE/iSCSIPortalUser=str:none:None
OVEHOSTED_STORAGE/imgSizeGB=str:185
OVEHOSTED_VM/vmDiskSizeGB=str:185
OVEHOSTED_STORAGE/lockspaceImageUUID=none:None
OVEHOSTED_STORAGE/lockspaceVolumeUUID=none:None
OVEHOSTED_STORAGE/metadataImageUUID=none:None
OVEHOSTED_STORAGE/metadataVolumeUUID=none:None
OVEHOSTED_STORAGE/storageDomainName=str:hosted_storage
OVEHOSTED_VM/OpenScapProfileName=none:None
OVEHOSTED_VM/applyOpenScapProfile=bool:False
OVEHOSTED_VM/automateVMShutdown=bool:True
OVEHOSTED_VM/cloudinitRootPwd=str:adminRoot!@#
OVEHOSTED_VM/cloudInitISO=str:generate
OVEHOSTED_VM/cloudinitExecuteEngineSetup=bool:True
OVEHOSTED_VM/cloudinitVMDNS=str:
OVEHOSTED_VM/cloudinitVMETCHOSTS=bool:True
OVEHOSTED_VM/cloudinitVMTZ=str:Asia/Seoul
OVEHOSTED_VM/emulatedMachine=str:pc
OVEHOSTED_VM/enableFips=bool:False
OVEHOSTED_VM/ovfArchive=str:
OVEHOSTED_VM/rootSshAccess=str:yes
OVEHOSTED_VM/rootSshPubkey=str:
OVEHOSTED_VM/vmCDRom=none:None
OVEHOSTED_VM/vmMemSizeMB=int:16384
OVEHOSTED_VM/vmVCpus=str:6
OVEHOSTED_NETWORK/host_name=str:hostname_value
OVEHOSTED_NETWORK/bridgeIf=str:bridgeIf_value
OVEHOSTED_NETWORK/gateway=str:gateway_value
OVEHOSTED_NETWORK/fqdn=str:fqdn_value
OVEHOSTED_VM/cloudinitInstanceDomainName=str:cloudinitInstanceDomainName_value
OVEHOSTED_VM/cloudinitInstanceHostName=str:cloudinitInstanceHostName_value
OVEHOSTED_VM/cloudinitVMStaticCIDR=str:cloudinitVMStaticCIDR_value
ANSWERS.CONF_EOF
}

task_answers.conf_nfs_fc_iscsi() {
MAC_ADDR=$(python3 -c "from ovirt_hosted_engine_setup import util as ohostedutil; print(ohostedutil.randomMAC())")
echo "OVEHOSTED_VM/vmMACAddr=str:$MAC_ADDR" | tee -a /etc/ovirt-hosted-engine/answers.conf.setup > /dev/null
current_hostname=$(hostname)
sed -i "s/OVEHOSTED_NETWORK\/host_name=str:hostname_value/OVEHOSTED_NETWORK\/host_name=str:${current_hostname}/g" /etc/ovirt-hosted-engine/answers.conf.setup | tee -a /etc/ovirt-hosted-engine/answers.conf.setup > /dev/null
sed -i "s/OVEHOSTED_VM\/cloudinitInstanceHostName=str:cloudinitInstanceHostName_value/OVEHOSTED_VM\/cloudinitInstanceHostName=str:${current_hostname}/g" /etc/ovirt-hosted-engine/answers.conf.setup | tee -a /etc/ovirt-hosted-engine/answers.conf.setup > /dev/null
echo
while true; do
    echo -n "> Engine VM Host name: "
    read fqdn
    if [ -n "$fqdn" ]; then
        sed -i "s/OVEHOSTED_NETWORK\/fqdn=str:fqdn_value/OVEHOSTED_NETWORK\/fqdn=str:${fqdn}/g" /etc/ovirt-hosted-engine/answers.conf.setup | tee -a /etc/ovirt-hosted-engine/answers.conf.setup > /dev/null
        break
    else
        echo "The hostname cannot be empty. Please enter a valid hostname."
    fi
done
echo
while true; do
    echo -n "> Engine VM IP: "
    read cloudinitVMStaticCIDR
    if validate_ip $cloudinitVMStaticCIDR; then
        sed -i "s/OVEHOSTED_VM\/cloudinitVMStaticCIDR=str:cloudinitVMStaticCIDR_value/OVEHOSTED_VM\/cloudinitVMStaticCIDR=str:${cloudinitVMStaticCIDR}/g" /etc/ovirt-hosted-engine/answers.conf.setup
        sed -i "s/OVEHOSTED_VM\/cloudinitInstanceDomainName=str:cloudinitInstanceDomainName_value/OVEHOSTED_VM\/cloudinitInstanceDomainName=str:${cloudinitVMStaticCIDR}/g" /etc/ovirt-hosted-engine/answers.conf.setup | tee -a /etc/ovirt-hosted-engine/answers.conf.setup > /dev/null
        break
    else
        echo "The IP address you entered is invalid. Please enter again."
    fi
done
if grep -q "^$cloudinitVMStaticCIDR" /etc/hosts; then
    sed -i "/^$cloudinitVMStaticCIDR /d" /etc/hosts
fi
if grep -q " $fqdn$" /etc/hosts; then
    sed -i "/ $fqdn$/d" /etc/hosts
fi
echo "$cloudinitVMStaticCIDR    $fqdn" | tee -a /etc/hosts > /dev/null
echo
echo "- NIC port available for bridge"
col1_width=8
col2_width=7
col3_width=17
col4_width=6
col5_width=9
col6_width=29
echo ==============================================================================================
printf "| %-${col1_width}s | %-${col2_width}s | %-${col3_width}s | %-${col4_width}s | %-${col5_width}s | %-${col6_width}s|\n" "DEVICE" "STATE" "CONNECTION" "SPEED" "DUPLEX" "IP"
echo +--------------------------------------------------------------------------------------------+
device_name=$(nmcli d | grep -Ev "lo|virbr|br-int|vdsmdummy|ip_vti|ovirtmgmt|bondscan" | tail -n +2 | awk '{print $1}')
for dev_name in $device_name; do
    interface=$dev_name
    state=$(ip -br a s $dev_name | grep -v lo | awk '{print $2}')
    connection=$(nmcli d | grep $dev_name | awk '{print $4}')
    speed=$(ethtool $dev_name | grep -i speed | awk '{print $2}' | awk '{ print substr($0, 1, length($0)-3) }')
    duplex=$(ethtool $dev_name | grep -i duplex | awk '{print $2}')
    ip4=$(ip -br a s $dev_name | grep -v lo | awk '{print $3}')
    printf "| %-${col1_width}s | %-${col2_width}s | %-${col3_width}s | %-${col4_width}s | %-${col5_width}s | %-${col6_width}s|\n" "$interface" "$state" "$connection" "$speed" "$duplex" "$ip4"
done
echo ==============================================================================================
while true; do
    default_bridge="bond0"
    echo -n "> Please indicate a NIC to set rutilvm bridge on. (ex: ${default_bridge}): "
    read -e -i "$default_bridge" bridgeIf
    device_list=$(nmcli d | tail -n +2 | awk '{print $1}' | grep -Ev 'lo|virbr')
    if [[ $device_list =~ (^|[[:space:]])$bridgeIf($|[[:space:]]) ]]; then
        sed -i "s/OVEHOSTED_NETWORK\/bridgeIf=str:bridgeIf_value/OVEHOSTED_NETWORK\/bridgeIf=str:${bridgeIf}/g" /etc/ovirt-hosted-engine/answers.conf.setup | tee -a /etc/ovirt-hosted-engine/answers.conf.setup > /dev/null
        break
    else
        echo "Invalid device. Please enter a valid device name."
        bridgeIf=""
    fi
done
gateway=$(ip route | grep default | awk '{print $3}')
if [ -n "$gateway" ]; then
    sed -i "s/OVEHOSTED_NETWORK\/gateway=str:gateway_value/OVEHOSTED_NETWORK\/gateway=str:${gateway}/g" /etc/ovirt-hosted-engine/answers.conf.setup | tee -a /etc/ovirt-hosted-engine/answers.conf.setup > /dev/null
else
    echo "Default gateway address not found."
    echo "Stop the installation."
    exit
fi
}

task_answers.conf_storage_type() {
	while true; do
		echo -n "> Please specify the storage you would like to use (fc, nfs, iscsi): "
		read -r engine_storage
		case $engine_storage in
			fc)
				cat << ANSWERS.CONF_FC_EOF >> /etc/ovirt-hosted-engine/answers.conf.setup
OVEHOSTED_STORAGE/connectionTimeout=int:180
OVEHOSTED_STORAGE/multipathSupport=bool:True
OVEHOSTED_STORAGE/pathPolicy=str:multibus
OVEHOSTED_STORAGE/failoverTimeout=int:60
OVEHOSTED_STORAGE/storageDomainConnection=none:None
OVEHOSTED_STORAGE/domainType=str:fc
OVEHOSTED_STORAGE/lunDetectType=str:fc
OVEHOSTED_STORAGE/fcPaths=int:2
OVEHOSTED_STORAGE/nfsVersion=str:auto
OVEHOSTED_STORAGE/iSCSIDiscoverUser=none:None
OVEHOSTED_STORAGE/iSCSIPortal=none:None
OVEHOSTED_STORAGE/iSCSIPortalIPAddress=none:None
OVEHOSTED_STORAGE/iSCSIPortalPort=none:None
OVEHOSTED_STORAGE/iSCSITargetName=none:None
OVEHOSTED_STORAGE/mntOptions=str:
OVEHOSTED_STORAGE/LunID=str:LunID_value
ANSWERS.CONF_FC_EOF
				while true; do
					multipath_output=$(multipath -ll)
					declare -a lun_list
					LunID_value=""
					size=""
					target_char=""
					target_name=""
					active_count=0
					while IFS= read -r line; do
						if [[ $line =~ ^(3[0-9a-fA-F]{31}|mpath[a-zA-Z0-9]+) ]]; then
							LunID_value=$(echo "$line" | awk '/^(3[0-9a-fA-F]{31}|mpath[a-zA-Z0-9]+)/{print $1}')
							size=""
							target_char=""
							target_name=""
							active_count=0
						fi
						if [[ $line =~ size=([0-9]+[MGTPEZY]) ]]; then
							size="${BASH_REMATCH[1]}"
						fi
						if [[ $line =~ (dm-[^[:space:]]+)[[:space:]]+([^[:space:],]+) ]]; then
							target_char="${BASH_REMATCH[2]}"
						fi
						if [[ $line =~ ,([^ ]+) ]]; then
							target_name="${BASH_REMATCH[1]}"
						fi
						if [[ $line =~ ^\|- || $line =~ ^\`- ]]; then
							active_count=$((active_count + 1))
						fi
						if [[ $line =~ ^\`- ]]; then
							lun_list+=("$LunID_value;$size;$target_char;$target_name;$active_count")
						fi
					done <<< "$multipath_output"
					if [ ${#lun_list[@]} -eq 0 ]; then
						echo "No LUNs available for selection."
						echo "1) LUN rescan"
						echo "2) Exit"
						echo -n "Select an action (1 or 2) "
						read -r user_choice
						if [ "$user_choice" == "1" ]; then
							task_lun_scan
						else
							echo "Aborts installation."
							exit 0
						fi
					else
						echo "The following LUNs have been found on the requested target:"
						index=1
						for lun in "${lun_list[@]}"; do
							IFS=';' read -r LunID_value size target_char target_name path_count <<< "$lun"
							printf "[%d]     %-35s %-5s %-10s %-20s\n" "$index" "$LunID_value" "$size" "$target_char" "$target_name"
							printf "                                     paths: %d active\n" "$path_count"
							((index++))
						done
						echo ""
						echo -n "Please select the destination LUN: "
						read -r selected_lun
						if [[ "$selected_lun" =~ ^[0-9]+$ ]] && ((selected_lun >= 1 && selected_lun <= index - 1)); then
							selected_lun_info="${lun_list[$selected_lun-1]}"
							IFS=';' read -r LunID_value size target_char target_name path_count <<< "$selected_lun_info"
							sed -i "s/OVEHOSTED_STORAGE\/LunID=str:LunID_value/OVEHOSTED_STORAGE\/LunID=str:${LunID_value}/g" /etc/ovirt-hosted-engine/answers.conf.setup
							break
						else
							echo "Invalid selection. Exiting."
							exit 1
						fi
					fi
				done
				break
				;;
			nfs)
				cat << ANSWERS.CONF_NFS_EOF >> /etc/ovirt-hosted-engine/answers.conf.setup
OVEHOSTED_STORAGE/LunID=none:None
OVEHOSTED_STORAGE/domainType=str:nfs
OVEHOSTED_STORAGE/iSCSIDiscoverUser=none:None
OVEHOSTED_STORAGE/iSCSIPortal=none:None
OVEHOSTED_STORAGE/iSCSIPortalIPAddress=none:None
OVEHOSTED_STORAGE/iSCSIPortalPort=none:None
OVEHOSTED_STORAGE/iSCSITargetName=none:None
OVEHOSTED_STORAGE/mntOptions=str:
OVEHOSTED_STORAGE/nfsVersion=str:auto
OVEHOSTED_STORAGE/storageDomainConnection=str:nfs_ip:nfs_storage_path
ANSWERS.CONF_NFS_EOF
				while true; do
					echo -n "Enter the NFS server IP: "
					read nfs_server_ip
					if validate_ip "$nfs_server_ip"; then
						output=$(showmount -e "$nfs_server_ip" | sed 1d)
						if [ -z "$output" ]; then
							echo "No response from NFS server. Check your IP or try again."
							while true; do
								echo "1) Retry"
								echo "2) Exit"
								read -p "Select (1 or 2): " retry_choice
								case $retry_choice in
									1)
										break
										;;
									2)
										echo "Aborts installation."
										exit 0
										;;
									*)
										echo "Invalid input. Please enter 1 or 2."
										;;
								esac
							done
							[[ $retry_choice -eq 1 ]] || break
							continue
						fi
						echo
						IFS=$'\n' mounts=($output)
						nfs_storage_path=""
						echo "Select the NFS mount path:"
						for i in "${!mounts[@]}"; do
							echo "[$((i+1))] ${mounts[$i]}"
						done
						while true; do
							echo
							read -p "Please select the destination path, or type no(n) to exit: " choice
							if [[ "$choice" =~ ^([nN][oO]|[nN])$ ]]; then
								return
							elif [[ "$choice" -gt 0 && "$choice" -le "${#mounts[@]}" ]]; then
								choice=$((choice-1))
								result=${mounts[$choice]}
								nfs_storage_path=$(echo "$result" | awk '{print $1}')
								break
							else
								echo "Invalid input. Please try again."
							fi
						done
						sed -i "s|nfs_ip|$nfs_server_ip|; s|nfs_storage_path|$nfs_storage_path|" /etc/ovirt-hosted-engine/answers.conf.setup
						break
					else
						echo "Invalid IP address. Check the NFS server IP address and try again."
					fi
				done
				break
				;;
			iscsi)
				cat << ANSWERS.CONF_iSCSI_EOF >> /etc/ovirt-hosted-engine/answers.conf.setup
OVEHOSTED_STORAGE/connectionTimeout=int:180
OVEHOSTED_STORAGE/multipathSupport=bool:true
OVEHOSTED_STORAGE/pathPolicy=str:multibus
OVEHOSTED_STORAGE/failoverTimeout=int:60
OVEHOSTED_STORAGE/storageDomainConnection=none:None
OVEHOSTED_STORAGE/domainType=str:iscsi
OVEHOSTED_STORAGE/lunDetectType=str:iscsi
OVEHOSTED_STORAGE/iSCSIPortal=str:1
OVEHOSTED_STORAGE/iSCSIPortalPort=str:3260
OVEHOSTED_STORAGE/iSCSIPortalPassword=str:none:None
OVEHOSTED_STORAGE/mntOptions=none:None
OVEHOSTED_STORAGE/iSCSIPortalIPAddress=str:iSCSIPortalIPAddress_value
OVEHOSTED_STORAGE/iSCSIDiscoverUser=str:iSCSIDiscoverUser_value
OVEHOSTED_STORAGE/iSCSIDiscoverPassword=str:iSCSIDiscoverPassword_value
OVEHOSTED_STORAGE/iSCSITargetName=str:iSCSITargetName_value
OVEHOSTED_STORAGE/hostedEngineLUNID=str:LunID_value
OVEHOSTED_STORAGE/LunID=str:LunID_value
ANSWERS.CONF_iSCSI_EOF
				echo
				echo -n "> Please specify the iSCSI discover user: "
				read iSCSIDiscoverUser
				sed -i "s/OVEHOSTED_STORAGE\/iSCSIDiscoverUser=str:iSCSIDiscoverUser_value/OVEHOSTED_STORAGE\/iSCSIDiscoverUser=str:${iSCSIDiscoverUser}/g" /etc/ovirt-hosted-engine/answers.conf.setup | tee -a /etc/ovirt-hosted-engine/answers.conf.setup > /dev/null
				echo
				echo -n "> Please specify the iSCSI discover password: "
				read iSCSIDiscoverPassword
				sed -i "s/OVEHOSTED_STORAGE\/iSCSIDiscoverPassword=str:iSCSIDiscoverPassword_value/OVEHOSTED_STORAGE\/iSCSIDiscoverPassword=str:${iSCSIDiscoverPassword}/g" /etc/ovirt-hosted-engine/answers.conf.setup | tee -a /etc/ovirt-hosted-engine/answers.conf.setup > /dev/null
				echo
				while true; do
					echo -n "> Please specify the iSCSI portal IP address: "
					read iSCSIPortalIPAddress
					if validate_ip "$iSCSIPortalIPAddress"; then
						sed -i "s/OVEHOSTED_STORAGE\/iSCSIPortalIPAddress=str:iSCSIPortalIPAddress_value/OVEHOSTED_STORAGE\/iSCSIPortalIPAddress=str:${iSCSIPortalIPAddress}/g" /etc/ovirt-hosted-engine/answers.conf.setup | tee -a /etc/ovirt-hosted-engine/answers.conf.setup > /dev/null
						break
					else
						echo "Invalid IP address. Please enter a valid IP address."
					fi
				done
				DISCOVERY_OUTPUT=$(iscsiadm -m discovery -t sendtargets -p "$iSCSIPortalIPAddress" -P 1 2>/dev/null)
				TARGETS=($(echo "$DISCOVERY_OUTPUT" | grep -oP '(?<=Target: ).+'))
				if [ ${#TARGETS[@]} -eq 0 ]; then
					echo "No iSCSI targets found for IP address $iSCSIPortalIPAddress."
					exit 1
				fi
				echo "The following targets have been found:"
				for i in "${!TARGETS[@]}"; do
					echo "[$((i+1))]     ${TARGETS[$i]}"
				done
				echo
				read -p "Please select a target: " SELECTION
				if ! [[ "$SELECTION" =~ ^[0-9]+$ ]] || [ "$SELECTION" -lt 1 ] || [ "$SELECTION" -gt ${#TARGETS[@]} ]; then
					echo "Invalid selection."
					exit 1
				fi
				iSCSITargetName="${TARGETS[$((SELECTION-1))]}"
				sed -i "s/OVEHOSTED_STORAGE\/iSCSITargetName=str:iSCSITargetName_value/OVEHOSTED_STORAGE\/iSCSITargetName=str:${iSCSITargetName}/g" /etc/ovirt-hosted-engine/answers.conf.setup | tee -a /etc/ovirt-hosted-engine/answers.conf.setup > /dev/null
				echo
				while true; do
					multipath_output=$(multipath -ll)
					declare -a lun_list
					LunID_value=""
					size=""
					target_char=""
					target_name=""
					active_count=0
					while IFS= read -r line; do
						if [[ $line =~ ^(3[0-9a-fA-F]{31}|mpath[a-zA-Z0-9]+) ]]; then
							LunID_value=$(echo "$line" | awk '/^(3[0-9a-fA-F]{31}|mpath[a-zA-Z0-9]+)/{print $1}')
							size=""
							target_char=""
							target_name=""
							active_count=0
						fi
						if [[ $line =~ size=([0-9]+[MGTPEZY]) ]]; then
							size="${BASH_REMATCH[1]}"
						fi
						if [[ $line =~ (dm-[^[:space:]]+)[[:space:]]+([^[:space:],]+) ]]; then
							target_char="${BASH_REMATCH[2]}"
						fi
						if [[ $line =~ ,([^ ]+) ]]; then
							target_name="${BASH_REMATCH[1]}"
						fi
						if [[ $line =~ ^\|- || $line =~ ^\`- ]]; then
							active_count=$((active_count + 1))
						fi
						if [[ $line =~ ^\`- ]]; then
							lun_list+=("$LunID_value;$size;$target_char;$target_name;$active_count")
						fi
					done <<< "$multipath_output"
					if [ ${#lun_list[@]} -eq 0 ]; then
						echo "No LUNs available for selection."
						echo "1) LUN rescan"
						echo "2) Exit"
						echo -n "Select an action (1 or 2) "
						read -r user_choice
						if [ "$user_choice" == "1" ]; then
							task_lun_scan
						else
							echo "Aborts installation."
							exit 0
						fi
					else
						echo "The following LUNs have been found on the requested target:"
						index=1
						for lun in "${lun_list[@]}"; do
							IFS=';' read -r LunID_value size target_char target_name path_count <<< "$lun"
							printf "[%d]     %-35s %-5s %-10s %-20s\n" "$index" "$LunID_value" "$size" "$target_char" "$target_name"
							printf "                                     paths: %d active\n" "$path_count"
							((index++))
						done
						echo ""
						echo -n "Please select the destination LUN: "
						read -r selected_lun
						if [[ "$selected_lun" =~ ^[0-9]+$ ]] && ((selected_lun >= 1 && selected_lun <= index - 1)); then
							selected_lun_info="${lun_list[$selected_lun-1]}"
							IFS=';' read -r LunID_value size target_char target_name path_count <<< "$selected_lun_info"
							sed -i "s/OVEHOSTED_STORAGE\/LunID=str:LunID_value/OVEHOSTED_STORAGE\/LunID=str:${LunID_value}/g" /etc/ovirt-hosted-engine/answers.conf.setup
							sed -i "s/OVEHOSTED_STORAGE\/hostedEngineLUNID=str:LunID_value/OVEHOSTED_STORAGE\/hostedEngineLUNID=str:${LunID_value}/g" /etc/ovirt-hosted-engine/answers.conf.setup
							break
						else
							echo "Invalid selection. Exiting."
							exit 1
						fi
					fi
				done
				break
				;;
		esac
	done
}

task_configuration_preview() {
	while true; do
		echo "== CONFIGURATION PREVIEW =="
		echo
		echo "Engine VM Hostname                 : "$fqdn
		echo "Engine VM IP                       : "$cloudinitVMStaticCIDR
		echo "Gateway address                    : "$gateway
		echo "Bridge interface                   : "$bridgeIf "($MAC_ADDR)"
		echo "Storage connection                 : "$engine_storage
		case $engine_storage in
			fc)
				echo "                                     $LunID_value"
				echo "                                     $size"
				;;
			iscsi)
				echo "                                     $TARGETS"
				echo "                                     $LunID_value"
				echo "                                     $size"
				;;
			nfs)
				echo "                                     $nfs_server_ip"
				echo "                                     $nfs_storage_path"
				;;
			*)
				;;
		esac
		echo
		read -p "Please confirm installation settings (Yes, No): " confirm_installation_yn
		case $confirm_installation_yn in
			yes|YES|y|Y|Yes)
				break
				;;
			no|NO|n|N|No)
				return 1
				;;
			*)
				echo "Invalid input. Please enter 'y' for yes or 'n' for no."
				;;
		esac
	done
}

task_certificate() {
while true; do
	read -s -p "$(tput setaf 5)engine root$(tput sgr0) account password : " cloudinitRootPwd
	echo
	if [[ -z "$cloudinitRootPwd" ]]; then
		echo "Password cannot be empty."
	elif [[ "$cloudinitRootPwd" =~ [[:space:]] ]]; then
		echo "Password should not contain spaces."
	else
        # /etc/ovirt-hosted-engine/hosted-engine.conf 파일에서 fqdn 문구로 시작하는 값 찾기
        fqdn_value=$(grep '^fqdn=' /etc/ovirt-hosted-engine/hosted-engine.conf | cut -d '=' -f2)
        # /etc/hosts 파일에서 해당 fqdn_value 검색 후 첫 번째 열 값 추출
        cloudinitVMStaticCIDR=$(grep -w "$fqdn_value" /etc/hosts | awk '{print $1}' | head -n 1)
		ping -c 1 $cloudinitVMStaticCIDR > /dev/null 2>&1
		if [[ $? -eq 0 ]]; then
			sshpass -p "$cloudinitRootPwd" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 root@$cloudinitVMStaticCIDR "exit" 2>/dev/null
			if [[ $? -eq 0 ]]; then
				break
			else
				echo "Engine connection failed."
			fi
		else
			echo "Unable to communicate with engine($cloudinitVMStaticCIDR)."
		fi
	fi
	read -p "Would you like to try again or exit? (y = try again / n = exit): " retry_choice
	if [[ "$retry_choice" =~ ^[nN]$ ]]; then
		exit 1
	fi
done
echo
echo "- Certificate Management"
col1_width=25
col2_width=25
col3_width=18
col4_width=13
# total col : 81
echo ==============================================================================================
printf "| %-${col1_width}s | %-${col2_width}s | %-${col3_width}s | %-${col4_width}s |\n" "Certificate" "Expiration date" "Expiration Period" "D-Day"
echo +--------------------------------------------------------------------------------------------+
VDSM_Certificate=$(openssl x509 -noout -enddate -in /etc/pki/vdsm/certs/vdsmcert.pem | sed 's/notAfter=//')
VDSM_CA_Certificate=$(openssl x509 -noout -enddate -in /etc/pki/vdsm/certs/cacert.pem | sed 's/notAfter=//')
Engine_Server_Certificate=$(/usr/bin/sshpass -p "$cloudinitRootPwd" ssh -o StrictHostKeyChecking=no root@$cloudinitVMStaticCIDR "openssl x509 -noout -enddate -in /etc/pki/ovirt-engine/certs/engine.cer" | sed 's/notAfter=//')
Engine_CA_Certificate=$(/usr/bin/sshpass -p "$cloudinitRootPwd" ssh -o StrictHostKeyChecking=no root@$cloudinitVMStaticCIDR "openssl x509 -noout -enddate -in /etc/pki/ovirt-engine/ca.pem" | sed 's/notAfter=//')
Engine_Certificate=$(openssl s_client -connect "$cloudinitVMStaticCIDR":443 -showcerts </dev/null 2>/dev/null | openssl x509 -noout -dates | grep notAfter | sed 's/notAfter=//')
calculate_days_remaining() {
	local expiry_date=$1
	local current_date=$(date -u +"%Y-%m-%d")
	local expiry_date_formatted=$(date -d "$expiry_date" +"%Y-%m-%d" 2>/dev/null)
	if [[ -n "$expiry_date_formatted" ]]; then
		local days_remaining=$(( ( $(date -d "$expiry_date_formatted" +%s) - $(date -d "$current_date" +%s) ) / 86400 ))
		echo "$days_remaining"
	else
		echo "N/A"
	fi
}
VDSM_Days_Remaining=$(calculate_days_remaining "$VDSM_Certificate")
VDSM_CA_Days_Remaining=$(calculate_days_remaining "$VDSM_CA_Certificate")
Engine_Server_Days_Remaining=$(calculate_days_remaining "$Engine_Server_Certificate")
Engine_CA_Days_Remaining=$(calculate_days_remaining "$Engine_CA_Certificate")
Engine_Days_Remaining=$(calculate_days_remaining "$Engine_Certificate")
printf "| %-${col1_width}s | %-${col2_width}s | %-${col3_width}s | %-${col4_width}s |\n" "VDSM Certificate" "$VDSM_Certificate" "5 years" "$VDSM_Days_Remaining days"
printf "| %-${col1_width}s | %-${col2_width}s | %-${col3_width}s | %-${col4_width}s |\n" "VDSM CA Certificate" "$VDSM_CA_Certificate" "10 years" "$VDSM_CA_Days_Remaining days"
printf "| %-${col1_width}s | %-${col2_width}s | %-${col3_width}s | %-${col4_width}s |\n" "Engine Certificate" "$Engine_Certificate" "398 days" "$Engine_Days_Remaining days"
printf "| %-${col1_width}s | %-${col2_width}s | %-${col3_width}s | %-${col4_width}s |\n" "Engine CA Certificate" "$Engine_CA_Certificate" "10 years" "$Engine_CA_Days_Remaining days"
printf "| %-${col1_width}s | %-${col2_width}s | %-${col3_width}s | %-${col4_width}s |\n" "Engine Server Certificate" "$Engine_Server_Certificate" "10 years" "$Engine_Server_Days_Remaining days"
echo ==============================================================================================
echo
}

# Function to display the main menu
rutilvm_main_menu() {
    clear
	col1_width=91
	echo ==============================================================================================
	echo -e "| \e[1mRutilVM Assistor\e[0m                                                                           |"
	echo +--------------------------------------------------------------------------------------------+
	printf "| %-${col1_width}s|\n"
	printf "| %-${col1_width}s|\n" "RutilVM 4.5.5"
	printf "| %-${col1_width}s|\n"
	printf "| %-${col1_width}s|\n"
	printf "| %-${col1_width}s|\n"
	printf "| %-${col1_width}s|\n"
	printf "| %-${col1_width}s|\n" "IT Information Technology Co., Ltd."
	printf "| %-${col1_width}s|\n" "https://www.ititinfo.com"
	printf "| %-${col1_width}s|\n"
	echo ==============================================================================================
	echo
    echo "1) RutilVM Host Configuration"
    echo "2) RutilVM Engine Configuration"
    echo "3) Management"
    echo "4) Exit"
    read -p "Select an option: " main_choice

    case $main_choice in
        1) host_configuration_menu ;;
        2) engine_configuration_menu ;;
        3) management_menu ;;
        4) exit 0 ;;
        *) echo "Invalid option. Please try again."; sleep 2; rutilvm_main_menu ;;
    esac
}

# Function to display the menu for RutilVM Host Configuration
host_configuration_menu() {
    clear
	product_name=$(dmidecode -s system-product-name | tr -d '\n')
	serial_number=$(dmidecode -s system-serial-number | tr -d '\n')
	processor=$(lscpu | grep "Model name" | awk -F: '{print $2}' | sed 's/^ *//' | sort -u)
	cpus=$(lscpu | awk -F: '/^CPU\(s\):/ {gsub(/^ +/, "", $2); print $2}')
	#cpus_core=$(($(lscpu | awk '/Core\(s\)/ {print $4}') * 2))
	total_memory=$(lsmem | awk '/Total online memory:/ {print $NF}')
	os_version=$(cat /etc/redhat-release)
	col1_width=91
	echo ==============================================================================================
	printf "| %-${col1_width}s|\n" "> RutilVM Host Configuration"
	echo +--------------------------------------------------------------------------------------------+
	printf "| %-${col1_width}s|\n"
	printf "| %-${col1_width}s|\n" "* Installation Warnings"
	printf "| %-${col1_width}s|\n" "  - Do Not Interrupt: Avoid force-closing or interrupting the installation"
	printf "| %-${col1_width}s|\n" "  - Input Carefully: Be cautious with hostnames, IP addresses, and passwords"
	printf "| %-${col1_width}s|\n" "  - Run as Root: It's recommended to run the script as 'root'"
	printf "| %-${col1_width}s|\n" "  - Stable Network Required: Ensure network stability during the setup"
	printf "| %-${col1_width}s|\n"
	printf "| %-${col1_width}s|\n" "* Host Information"
	printf "| %-${col1_width}s|\n" "  - System Product Name   : $product_name"
	printf "| %-${col1_width}s|\n" "  - Serial Number         : $serial_number"
	printf "| %-${col1_width}s|\n" "  - Processor             : $processor * $cpus"
	printf "| %-${col1_width}s|\n" "  - Memory                : $total_memory"
	printf "| %-${col1_width}s|\n"
	echo ==============================================================================================
	echo
    task_host_add
	echo
	task_bonding
	echo
	task_repository
	echo
	task_ntp
	echo
    echo "1) Back to Main Menu"
    echo "2) Exit"
    read -p "Select an option: " sub_choice

    case $sub_choice in
        1) rutilvm_main_menu ;;
        2) exit 0 ;;
        *) echo "Invalid option. Please try again."; sleep 2; host_configuration_menu ;;
    esac
}

# Function to display the menu for RutilVM Engine Configuration
engine_configuration_menu() {
    clear
	col1_width=91
	echo ==============================================================================================
	printf "| %-${col1_width}s|\n" "> RutilVM Engine Configuration"
	echo +--------------------------------------------------------------------------------------------+
	printf "| %-${col1_width}s|\n"
	printf "| %-${col1_width}s|\n" "* Pre-requisite Check"
	printf "| %-${col1_width}s|\n" "  - Hardware Requirements:"
	printf "| %-${col1_width}s|\n" "    Ensure the system meets minimum CPU, memory, and storage specifications."
	printf "| %-${col1_width}s|\n" "    It is recommended to have at least two network interfaces on the host system."
	printf "| %-${col1_width}s|\n"
	printf "| %-${col1_width}s|\n" "  - Storage Requirements:"
	printf "| %-${col1_width}s|\n" "    Prepare shared storage such as FC, iSCSI, or NFS."
	printf "| %-${col1_width}s|\n" "    Shared storage is mandatory for the Self-Hosted Engine environment."
	printf "| %-${col1_width}s|\n" "    The required shared storage capacity is 200GB."
	printf "| %-${col1_width}s|\n"
	printf "| %-${col1_width}s|\n" "  - Network Requirements:"
	printf "| %-${col1_width}s|\n" "    Use a static IP, and ensure the FQDN (DNS configuration) is properly set."
	printf "| %-${col1_width}s|\n" "    Open firewall ports for SSH, oVirt Engine, etc."
	printf "| %-${col1_width}s|\n"
	echo -n ==============================================================================================
	task_answers.conf
	echo
	task_answers.conf_nfs_fc_iscsi
	echo
	task_answers.conf_storage_type
	echo
	task_configuration_preview
	if [[ $? -eq 1 ]]; then
		break
	fi
	echo
	if ! dnf list installed ovirt-engine-appliance &> /dev/null; then
		rpm_file=$(dnf --quiet repoquery --location ovirt-engine-appliance | sed 's|^file://||' 2>/dev/null)
		if [[ -n "$rpm_file" && -f "$rpm_file" ]]; then
			echo "[ INFO  ] TASK [rutilvm.hosted_engine_setup : Install the RutilVM engine package]"
			dnf install -y ovirt-engine-appliance >/dev/null 2>&1
			if dnf list installed ovirt-engine-appliance &> /dev/null; then
				echo -e "\nRutilVM engine package installation done."
			else
				echo "[WARNING] RutilVM engine package installation failed"
				echo "[WARNING] Aborts installation"
				exit 1
			fi
		else
			echo "[WARNING] The RutilVM engine package is not available in the repository"
			echo "[WARNING] Aborts installation"
			exit 1
		fi
	fi
	echo
	TIMESTAMP=$(date +%Y%m%d%H%M%S)
	if [ -f /etc/ovirt-hosted-engine/answers.conf ]; then
		mv /etc/ovirt-hosted-engine/answers.conf /etc/ovirt-hosted-engine/answers.conf.$TIMESTAMP
		if [ $? -ne 0 ]; then
			echo "[WARNING] Failed to create backup of answers.conf" >&2
			exit 1
		fi
	fi
	cp /etc/ovirt-hosted-engine/answers.conf.setup /etc/ovirt-hosted-engine/answers.conf
	if [ $? -ne 0 ]; then
		echo "[WARNING] Failed to copy answers.conf" >&2
		exit 1
	fi
#	hosted-engine --deploy --4 --ansible-extra-vars=he_offline_deployment=true --config-append=/etc/ovirt-hosted-engine/answers.conf

hosted-engine --deploy --4 --ansible-extra-vars=he_offline_deployment=true --config-append=/etc/ovirt-hosted-engine/answers.conf | \
awk '
  BEGIN {
    skip_next_line = 0;
    skipping_consecutive = 0;
  }
  {
    # Check for lines that contain specific configuration headings
    if ($0 ~ /STORAGE CONFIGURATION/ || $0 ~ /HOST NETWORK CONFIGURATION/ || $0 ~ /VM CONFIGURATION/ || $0 ~ /HOSTED ENGINE CONFIGURATION/) {
      next;
    }
    
    # Check for lines that only contain whitespace
    if ($0 ~ /^\s*$/) {
      next;
    }
    
    # Check for "Fail" line and prepare to skip the next line
    if ($0 ~ /TASK \[ovirt.ovirt.hosted_engine_setup : Fail/) {
      skip_next_line = 1;
      next;
    }
    
    # Check for "skipping: [localhost]" line
    if ($0 ~ /\[ INFO  \] skipping: \[localhost\]/) {
      if (skip_next_line) {
        skip_next_line = 0; # Skip the line following "Fail" message
        next;
      }
      
      if (skipping_consecutive) {
        next;
      }
      
      # Check if the next line is also "skipping: [localhost]"
      getline next_line;
      if (next_line ~ /\[ INFO  \] skipping: \[localhost\]/) {
        skipping_consecutive = 1;
      } else {
        skipping_consecutive = 0;
      }
      next;
    } else {
      skipping_consecutive = 0;
    }
    
    # Print the line if it passed all the conditions
    print;
  }'


	TIMEOUT=30
	INTERVAL=1
	elapsed_time=0
	cloudinitRootPwd=adminRoot!@#
	echo "[ INFO  ] TASK [rutilvm.hosted_engine_setup : Checking connection to engine]"
	while [ $elapsed_time -lt $TIMEOUT ]; do
		if ping -c 1 $cloudinitVMStaticCIDR &> /dev/null; then
			echo "[ INFO  ] ok: [localhost]"
			sleep 2
			echo "[ INFO  ] TASK [rutilvm.hosted_engine_setup : File system adjustment start]"
			/usr/bin/sshpass -p $cloudinitRootPwd ssh -o StrictHostKeyChecking=no root@$cloudinitVMStaticCIDR /usr/sbin/parted -s /dev/vda resizepart 2 100% >/dev/null 2>&1
			/usr/bin/sshpass -p $cloudinitRootPwd ssh -o StrictHostKeyChecking=no root@$cloudinitVMStaticCIDR /usr/sbin/pvresize /dev/vda2 >/dev/null 2>&1
			/usr/bin/sshpass -p $cloudinitRootPwd ssh -o StrictHostKeyChecking=no root@$cloudinitVMStaticCIDR /usr/sbin/lvextend -L +40G /dev/ovirt/root >/dev/null 2>&1
			/usr/bin/sshpass -p $cloudinitRootPwd ssh -o StrictHostKeyChecking=no root@$cloudinitVMStaticCIDR /usr/sbin/lvextend -L +45G /dev/ovirt/var >/dev/null 2>&1
			/usr/bin/sshpass -p $cloudinitRootPwd ssh -o StrictHostKeyChecking=no root@$cloudinitVMStaticCIDR /usr/sbin/lvextend -L +30G /dev/ovirt/log >/dev/null 2>&1
			/usr/bin/sshpass -p $cloudinitRootPwd ssh -o StrictHostKeyChecking=no root@$cloudinitVMStaticCIDR /usr/sbin/xfs_growfs / >/dev/null 2>&1
			/usr/bin/sshpass -p $cloudinitRootPwd ssh -o StrictHostKeyChecking=no root@$cloudinitVMStaticCIDR /usr/sbin/xfs_growfs /var >/dev/null 2>&1
			/usr/bin/sshpass -p $cloudinitRootPwd ssh -o StrictHostKeyChecking=no root@$cloudinitVMStaticCIDR /usr/sbin/xfs_growfs /var/log >/dev/null 2>&1
			echo "[ INFO  ] changed: [localhost]"
			/usr/bin/sshpass -p $cloudinitRootPwd ssh -o StrictHostKeyChecking=no root@$cloudinitVMStaticCIDR /usr/bin/mkdir -p /var/share/pkg/rutilvm >/dev/null 2>&1
			echo "[ INFO  ] TASK [rutilvm.hosted_engine_setup : Preparing for engine rebalancing]"
			/usr/bin/sshpass -p $cloudinitRootPwd scp -o StrictHostKeyChecking=no /var/share/pkg/rutilvm/engine.zip root@$cloudinitVMStaticCIDR:/var/share/pkg/rutilvm/ >/dev/null 2>&1
			/usr/bin/sshpass -p $cloudinitRootPwd ssh -o StrictHostKeyChecking=no root@$cloudinitVMStaticCIDR "export UNZIP_DISABLE_ZIPBOMB_DETECTION=TRUE; /usr/bin/unzip -q -P 'itinfo1!' -o /var/share/pkg/rutilvm/engine.zip -d /var/share/pkg/rutilvm/" >/dev/null 2>&1
			echo "[ INFO  ] ok: [localhost]"
			/usr/bin/sshpass -p $cloudinitRootPwd ssh -o StrictHostKeyChecking=no root@$cloudinitVMStaticCIDR "/usr/bin/chmod 755 /var/share/pkg/rutilvm/*.sh"
			/usr/bin/sshpass -p $cloudinitRootPwd ssh -o StrictHostKeyChecking=no root@$cloudinitVMStaticCIDR "/usr/bin/chmod 755 /var/share/pkg/rutilvm/rutilvm-engine-setup"
			/usr/bin/sshpass -p $cloudinitRootPwd ssh -tt -o StrictHostKeyChecking=no root@$cloudinitVMStaticCIDR /var/share/pkg/rutilvm/repository.sh 2>&1 | grep -v "Connection to $cloudinitVMStaticCIDR closed." | tee -a rutilvm-engine-setup.log
			/usr/bin/sshpass -p $cloudinitRootPwd ssh -tt -o StrictHostKeyChecking=no root@$cloudinitVMStaticCIDR /var/share/pkg/rutilvm/firewall.sh 2>&1 | grep -v "Connection to $cloudinitVMStaticCIDR closed." | tee -a rutilvm-engine-setup.log
			/usr/bin/sshpass -p $cloudinitRootPwd ssh -tt -o StrictHostKeyChecking=no root@$cloudinitVMStaticCIDR /var/share/pkg/rutilvm/instaill_docker.sh 2>&1 | grep -v "Connection to $cloudinitVMStaticCIDR closed." | tee -a rutilvm-engine-setup.log
			/usr/bin/sshpass -p $cloudinitRootPwd ssh -tt -o StrictHostKeyChecking=no root@$cloudinitVMStaticCIDR /var/share/pkg/rutilvm/install_docker-compose.sh 2>&1 | grep -v "Connection to $cloudinitVMStaticCIDR closed." | tee -a rutilvm-engine-setup.log
			/usr/bin/sshpass -p $cloudinitRootPwd ssh -tt -o StrictHostKeyChecking=no root@$cloudinitVMStaticCIDR /var/share/pkg/rutilvm/docker_setting.sh 2>&1 | grep -v "Connection to $cloudinitVMStaticCIDR closed." | tee -a rutilvm-engine-setup.log
			/usr/bin/sshpass -p $cloudinitRootPwd ssh -tt -o StrictHostKeyChecking=no root@$cloudinitVMStaticCIDR /var/share/pkg/rutilvm/load_doceker_images.sh 2>&1 | grep -v "Connection to $cloudinitVMStaticCIDR closed." | tee -a rutilvm-engine-setup.log
			/usr/bin/sshpass -p $cloudinitRootPwd ssh -tt -o StrictHostKeyChecking=no root@$cloudinitVMStaticCIDR /var/share/pkg/rutilvm/docker-compose_up.sh 2>&1 | grep -v "Connection to $cloudinitVMStaticCIDR closed." | tee -a rutilvm-engine-setup.log
			/usr/bin/sshpass -p $cloudinitRootPwd ssh -tt -o StrictHostKeyChecking=no root@$cloudinitVMStaticCIDR /var/share/pkg/rutilvm/sso_set.sh 2>&1 | grep -v "Connection to $cloudinitVMStaticCIDR closed." | tee -a rutilvm-engine-setup.log
			/usr/bin/sshpass -p $cloudinitRootPwd ssh -tt -o StrictHostKeyChecking=no root@$cloudinitVMStaticCIDR /var/share/pkg/rutilvm/pg_hba_authentication_set.sh 2>&1 | grep -v "Connection to $cloudinitVMStaticCIDR closed." | tee -a rutilvm-engine-setup.log
			/usr/bin/sshpass -p $cloudinitRootPwd ssh -tt -o StrictHostKeyChecking=no root@$cloudinitVMStaticCIDR /var/share/pkg/rutilvm/db_permissions_set.sh 2>&1 | grep -v "Connection to $cloudinitVMStaticCIDR closed." | tee -a rutilvm-engine-setup.log
			/usr/bin/sshpass -p $cloudinitRootPwd ssh -tt -o StrictHostKeyChecking=no root@$cloudinitVMStaticCIDR /var/share/pkg/rutilvm/branding.sh 2>&1 | grep -v "Connection to $cloudinitVMStaticCIDR closed." | tee -a rutilvm-engine-setup.log
			/usr/bin/sshpass -p $cloudinitRootPwd ssh -tt -o StrictHostKeyChecking=no root@$cloudinitVMStaticCIDR /var/share/pkg/rutilvm/block_ovirt-engine.sh 2>&1 | grep -v "Connection to $cloudinitVMStaticCIDR closed." | tee -a rutilvm-engine-setup.log
			/usr/bin/sshpass -p $cloudinitRootPwd ssh -tt -o StrictHostKeyChecking=no root@$cloudinitVMStaticCIDR /var/share/pkg/rutilvm/tomcat_log_level.sh 2>&1 | grep -v "Connection to $cloudinitVMStaticCIDR closed." | tee -a rutilvm-engine-setup.log
			/usr/bin/sshpass -p $cloudinitRootPwd ssh -tt -o StrictHostKeyChecking=no root@$cloudinitVMStaticCIDR /var/share/pkg/rutilvm/tomcat_ip_set.sh 2>&1 | grep -v "Connection to $cloudinitVMStaticCIDR closed." | tee -a rutilvm-engine-setup.log
			/usr/bin/sshpass -p $cloudinitRootPwd ssh -tt -o StrictHostKeyChecking=no root@$cloudinitVMStaticCIDR /var/share/pkg/rutilvm/history.sh 2>&1 | grep -v "Connection to $cloudinitVMStaticCIDR closed."| tee -a rutilvm-engine-setup.log
			/usr/bin/sshpass -p $cloudinitRootPwd ssh -tt -o StrictHostKeyChecking=no root@$cloudinitVMStaticCIDR /var/share/pkg/rutilvm/engine_backup.sh 2>&1 | grep -v "Connection to $cloudinitVMStaticCIDR closed." | tee -a rutilvm-engine-setup.log					
			/usr/bin/sshpass -p $cloudinitRootPwd ssh -o StrictHostKeyChecking=no root@$cloudinitVMStaticCIDR /usr/bin/find /var/share/pkg/rutilvm -mindepth 1 ! -name '*.zip' -exec rm -rf {} +
			echo "RutilVM Hosted Engine successfully deployed"
			exit 0
		fi
		sleep $INTERVAL
		elapsed_time=$((elapsed_time + INTERVAL))
	done
	echo "[ ERROR ] Unable to connect to engine within $TIMEOUT seconds. Installation failed"
	exit 1
}


# Function to display the menu for Maintenance
management_menu_banner=$(
	col1_width=91
	echo ==============================================================================================
	echo -e "|\e[1m > Management\e[0m                                                                              |"
	echo +--------------------------------------------------------------------------------------------+
	printf "| %-${col1_width}s|\n"
	printf "| %-${col1_width}s|\n" "RutilVM Node Status Check    -> Engine start and node status check"
	printf "| %-${col1_width}s|\n" "RutilVM Node Daemon Status   -> Troubleshooting Engine Starting or Connecting"
	printf "| %-${col1_width}s|\n" "RutilVM Node Daemon Reload   -> libvirtd, vdsmd, ovirt-ha-broker, ovirt-ha-agent"
	printf "| %-${col1_width}s|\n" "RutilVM Certificate          -> Check certificate expiration date"
	printf "| %-${col1_width}s|\n" "Start a Collection           -> Collect data to solve problems"
	printf "| %-${col1_width}s|\n"
	echo ==============================================================================================
)

management_menu() {
    clear
	echo "$management_menu_banner"
	echo
    echo "1) RutilVM Node Status"
    echo "2) RutilVM Node Daemon Status"
    echo "3) RutilVM Node Daemon Reload"
    echo "4) RutilVM Certificate"
    echo "5) Data collection"
    echo "6) Back to Main Menu"
    echo "7) Exit"
    read -p "Select an option: " sub_choice

    case $sub_choice in
        1) node_status_menu ;;
        2) node_daemon_status_menu ;;
        3) node_daemon_reload_menu ;;
        4) certificate_menu ;;
        5) data_collection_menu ;;
        6) rutilvm_main_menu ;;
        7) exit 0 ;;
        *) echo "Invalid option. Please try again."; sleep 2; management_menu ;;
    esac
}

# Function to display the menu for RutilVM Node Status
node_status_menu() {
	while true; do
		if [[ -f /etc/ovirt-hosted-engine/hosted-engine.conf ]]; then
				clear
				hosted-engine --vm-status | grep -Ev 'timestamp|conf_on_shared_storage|crc32|local_conf_timestamp|metadata_|stopped='
		else
			echo
			echo "You must run deploy first"; sleep 2; management_menu
		fi
		echo
		while true; do
			echo "1) Back to Previous Menu"
			echo "2) Exit"
			read -p "Select an option: " back_choice
	
			case $back_choice in
				1) management_menu; break ;;
				2) exit 0 ;;
				*) echo "Invalid option. Please try again."; echo ;;
			esac
		done
	done
}

# Function to display the menu for RutilVM Node Daemon Status
node_daemon_status_menu() {
	clear
	while true; do
		systemctl status ovirt-ha-agent | more
		echo
		read -n1 -r -p "Press the any key to proceed to the next step..." key
		echo
		echo ----------------------------------------------------------------------------------------------
		echo
		systemctl status ovirt-ha-broker | more
		echo
		read -n1 -r -p "Press the space bar to proceed to the next step..." key
		echo
		echo ----------------------------------------------------------------------------------------------
		echo
		systemctl status vdsmd | more
		echo
		read -n1 -r -p "Press the space bar to proceed to the next step..." key
		echo
		echo ----------------------------------------------------------------------------------------------
		echo
		systemctl status libvirtd | more
		echo
		while true; do
			echo "1) Back to Previous Menu"
			echo "2) Exit"
			read -p "Select an option: " back_choice
	
			case $back_choice in
				1) management_menu; break ;;
				2) exit 0 ;;
				*) echo "Invalid option. Please try again.";echo;;
			esac
		done
	done
}

# Function to display the menu for RutilVM Node Daemon Reload
node_daemon_reload_menu() {
    clear
	col1_width=91
	echo ==============================================================================================
	echo -e "|\e[1m > RutilVM Node Daemon Reload\e[0m                                                               |"
	echo +--------------------------------------------------------------------------------------------+
	printf "| %-${col1_width}s|\n"
	printf "| %-${col1_width}s|\n" "ovirt-ha-agent              -> oVirt Hosted Engine High Availability Monitoring Agent"
	printf "| %-${col1_width}s|\n" "ovirt-ha-broker             -> oVirt Hosted Engine High Availability Communications Broker"
	printf "| %-${col1_width}s|\n" "vdsmd                       -> Virtual Desktop Server Manager"
	printf "| %-${col1_width}s|\n" "libvirtd                    -> Virtualization daemon"
	printf "| %-${col1_width}s|\n"
	printf "| %-${col1_width}s|\n" "- CAUTION -"
	printf "| %-${col1_width}s|\n" "Even if the libvirtd daemon is restarted, the virtual machines that are already running wi"
	printf "| %-${col1_width}s|\n" "ll not be stopped. However, in certain situations, there may be a temporary disruption in "
	printf "| %-${col1_width}s|\n" "connections or the management interface."
	printf "| %-${col1_width}s|\n"
	echo ==============================================================================================
	echo
    echo "1) ovirt-ha-agent Reload"
    echo "2) ovirt-ha-broker Reload"
    echo "3) vdsmd Reload"
    echo "4) libvirtd Reload"
    echo "5) Back to Previous Menu"
    echo "6) Exit"
    read -p "Select an option: " back_choice

    case $back_choice in
        1) ovirt-ha-agent_menu ;;
        2) ovirt-ha-broker_menu ;;
        3) vdsmd_menu ;;
        4) libvirtd_menu ;;
        5) management_menu ;;
        6) exit 0 ;;
        *) echo "Invalid option. Please try again."; sleep 2; node_daemon_reload_menu ;;
    esac
}

# Function to display the menu for ovirt-ha-agent Reload
ovirt-ha-agent_menu() {
	clear
	while true; do
		echo "* ovirt-ha-agent.service daemon restart" 
		systemctl restart ovirt-ha-agent
		echo
		while true; do
			systemctl status ovirt-ha-agent
			echo
			echo "1) Back to Previous Menu"
			echo "2) Exit"
			read -p "Select an option: " sub_choice
		
			case $sub_choice in
				1) node_daemon_reload_menu ;;
				2) exit 0 ;;
				*) echo "Invalid option. Please try again."; sleep 2; ovirt-ha-agent_menu ;;
			esac
		done
	done
}

# Function to display the menu for RutilVM ovirt-ha-broker Reload
ovirt-ha-broker_menu() {
	clear
	while true; do
		echo "* ovirt-ha-broker.service daemon restart"
		systemctl restart ovirt-ha-broker
		echo
		systemctl status ovirt-ha-broker
		echo
		while true; do
			echo "1) Back to Previous Menu"
			echo "2) Exit"
			read -p "Select an option: " sub_choice
		
			case $sub_choice in
				1) node_daemon_reload_menu ;;
				2) exit 0 ;;
				*) echo "Invalid option. Please try again."; sleep 2; ovirt-ha-broker_menu ;;
			esac
		done
	done
}

# Function to display the menu for vdsmd Reload
vdsmd_menu() {
    clear
	while true; do
		echo "* vdsmd.service daemon restart"
		systemctl restart vdsmd
		echo
		systemctl status vdsmd
		echo
		while true; do
			echo "1) Back to Previous Menu"
			echo "2) Exit"
			read -p "Select an option: " sub_choice
		
			case $sub_choice in
				1) node_daemon_reload_menu ;;
				2) exit 0 ;;
				*) echo "Invalid option. Please try again."; sleep 2; vdsmd_menu ;;
			esac
		done
	done
}

# Function to display the menu for libvirtd Reload
libvirtd_menu() {
    clear
	while true; do
		echo "* libvirtd.service daemon restart"
		systemctl restart libvirtd
		echo
		systemctl status libvirtd
		echo
		while true; do
			echo "1) Back to Previous Menu"
			echo "2) Exit"
			read -p "Select an option: " sub_choice
		
			case $sub_choice in
				1) node_daemon_reload_menu ;;
				2) exit 0 ;;
				*) echo "Invalid option. Please try again."; sleep 2; libvirtd_menu ;;
			esac
		done
	done
}

# Function to display the menu for RutilVM Certificate
certificate_menu_banner=$(
    clear
	col1_width=91
	echo ==============================================================================================
	echo -e "|\e[1m > RutilVM Certificate\e[0m                                                                      |"
	echo +--------------------------------------------------------------------------------------------+
	printf "| %-${col1_width}s|\n"
	printf "| %-${col1_width}s|\n" "                                Certificate Renewal Policy"
	printf "| %-${col1_width}s|\n" 
	printf "| %-${col1_width}s|\n" "－ RutilVM automatically requires the renewal of certificates that are set to expire within"
	printf "| %-${col1_width}s|\n" "   30 days."
	printf "| %-${col1_width}s|\n" "－ If the engine-setup command is executed within 30 days before the expiration date, the  "
	printf "| %-${col1_width}s|\n" "   PKI CONFIGURATION stage will be activated."
	printf "| %-${col1_width}s|\n" "－ If more than 30 days remain before the expiration date, the PKI stage will be skipped   "
	printf "| %-${col1_width}s|\n" "   when running the engine-setup command."
	printf "| %-${col1_width}s|\n" "－ oVirt checks the expiration date of both the existing CA certificate and the server     " 
	printf "| %-${col1_width}s|\n" "   certificate. If either certificate is set to expire within 30 days, renewal is required."
	printf "| %-${col1_width}s|\n" "－ Failure to renew the certificates may result in the inability to access the web         "
	printf "| %-${col1_width}s|\n" "   interface and disruption of certain services, so it is crucial to renew them in advance."
	printf "| %-${col1_width}s|\n"
	echo ==============================================================================================
	echo
)

certificate_menu() {
	while true; do
		echo
		if [[ ! -f /etc/ovirt-hosted-engine/hosted-engine.conf ]]; then
			echo "You must run deploy first."; sleep 2; management_menu
		else
			clear
			echo "$certificate_menu_banner"
			task_certificate
		fi
		echo
		while true; do
			echo "1) Back to Previous Menu"
			echo "2) Exit"
			read -p "Select an option: " back_choice
		
			case $back_choice in
				1) management_menu ;;
				2) exit 0 ;;
				*) echo "Invalid option. Please try again." ; echo ;
			esac
		done
	done
}

# Function to display the menu for Data collection
data_collection_menu() {
#	clear
	while true; do
#		echo "$management_menu_banner"
		echo
		echo "Start collecting data from the $(hostname)."
		echo "No changes will be made to system configuration."
		echo
		yes | sosreport -a | grep -Ev "made|version|command|archive|centos|CentOS|representative|policies|sensitive|organization|party|plugin|ENTER|Optionally|Redirecting" | sed '/^$/d'
		echo
		while true; do
			echo "1) Back to Previous Menu"
			echo "2) Exit"
			read -p "Select an option: " back_choice
		
			case $back_choice in
				1) management_menu ; break ;;
				2) exit 0 ;;
				*) echo "Invalid option. Please try again."; echo ;;
			esac
		done
	done
}

# Get the script name (filename) without the path
RUTILVM=$(basename "$0")

# Display usage help message
usage() {
    cat << EOF
Usage: /usr/bin/rutilvm [--help] <command> [<command-args>]
    --help
        show this help message.

    The available commands are:
        --deploy [options]
            run rutilvm-hosted-engine deployment.
        --deploy-engine
            Run rutilvm-engine deployment.
            Deploy the engine using a standardized configuration rather than a 
            custom configuration, making engine deployment easier.
        --deploy-host
            Perform basic configuration on the host to enable engine installation, 
            including the installation of essential packages required for network, 
            storage, and engine deployment.
        --vm-start
            start VM on this host
        --vm-start-paused
            start VM on this host with qemu paused.
        --vm-shutdown
            gracefully shutdown the VM on this host.
        --vm-poweroff
            forcefully poweroff the VM on this host.
        --vm-status [--json]
            VM status according to the HA agent. If --json is given, the
            output will be in machine-readable (JSON) format.
        --add-console-password [--password=<password>]
            Create a temporary password for vnc connection. If
            --password is given, the password will be set to the value
            provided. Otherwise, if it is set, the environment variable
            OVIRT_HOSTED_ENGINE_CONSOLE_PASSWORD will be used. As a last
            resort, the password will be read interactively.
        --config-append=<file>
            Load extra configuration files or answer file.
        --check-deployed
            Check whether the hosted engine has been deployed already.
        --check-liveliness
            Checks liveliness page of engine.
        --connect-storage
            Connect the hosted engine storage domain.
        --disconnect-storage
            Disconnect the hosted engine storage domain.
        --console
            Open the configured serial console.
        --set-maintenance --mode=<mode>
            Set maintenance status to the specified mode (global/local/none).
        --set-shared-config <key> <value> [--type=<type>]
            Set specified key to the specified value. If the key is duplicated
            in several files a type must be provided.
        --get-shared-config <key> [--type=<type>]
            Get specified key's value. If the key is duplicated in several
            files a type must be provided.
        --reinitialize-lockspace
            Make sure all hosted engine agents are down and reinitialize the
            sanlock lockspaces.
        --clean-metadata
            Remove the metadata for the current host's agent from the global
            status database. This makes all other hosts forget about this
            host.
        --check-cert
            Check the certificate and verify the expiration date.
        --collect
            It collects system status, configuration, logs, and diagnostic 
            data to create a compressed archive file for troubleshooting 
            and diagnosing system issues.
EOF
}

help_deploy() {
    cat << EOF
Usage: $0 [--help] <command> [<command-args>]
    --deploy [args]
        Run rutilvm-engine deployment.

        --config-append=<file>
            Load extra configuration files.
        --generate-answer=<file>
            Generate answer file.
        --restore-from-file=<file>
            Restore an engine backup file during the deployment.
        --4
            Force IPv4 on dual stack env.
        --6
            Force IPv6 on dual stack env.
        --ansible-extra-vars=DATA
            Pass '--extra-vars=DATA' to all ansible calls.
            DATA can be anything that ansible can accept - var=value,
            @file, JSON/YAML.
            Please note: Using this option is supported only
            with specific values as documented elsewhere.
            Passing arbitrary values might conflict with existing
            variables.
        --host
            Perform basic configuration on the host to enable engine installation, 
            including the installation of essential packages required for network, 
            storage, and engine deployment.
        --engine
            Deploy the engine using a standardized configuration rather than a 
            custom configuration, making engine deployment easier.
EOF
}

help_deploy-engine() {
    cat << EOF
Usage: $0 --deploy-engine
    --deploy-engine
        Run rutilvm-engine deployment.
        Deploy the engine using a standardized configuration rather than a 
        custom configuration, making engine deployment easier.
EOF
}

help_deploy-host() {
    cat << EOF
Usage: $0 --deploy-host
    --deploy-host
        Perform basic configuration on the host to enable engine installation, 
        including the installation of essential packages required for network, 
        storage, and engine deployment.
EOF
}

help_vm-start() {
    cat << EOF
Usage: $0 --vm-start
    Start the engine VM on this host.
    Available only after deployment has completed.

    --vm-conf=<file>
        Load an alternative vm.conf file as a recovery action.
EOF
}

help_vm-start-paused() {
    cat << EOF
Usage: $0 --vm-start-paused
    Start the engine VM in paused state on this host.
    Available only after deployment has completed.
EOF
}

help_vm-shutdown() {
    cat << EOF
Usage: $0 --vm-shutdown
    Gracefully shut down the engine VM on this host.
    Available only after deployment has completed.
EOF
}

help_vm-poweroff() {
    cat << EOF
Usage: $0 --vm-poweroff
    Forcefully power off the engine VM on this host.
    Available only after deployment has completed.
EOF
}

help_vm-status() {
    cat << EOF
Usage: $0 --vm-status [--json]
    Report the status of the engine VM according to the HA agent.
    Available only after deployment has completed.

    If --json is given, the output will be in machine-readable (JSON) format.
EOF
}

help_add-console-password() {
    cat << EOF
Usage: $0 --add-console-password [--password=<password>]
    Create a temporary password for vnc connection.

    If --password is given, the password will be set to the value provided.
    Otherwise, if it is set, the environment variable
    OVIRT_HOSTED_ENGINE_CONSOLE_PASSWORD will be used. As a last resort, the
    password will be read interactively.
    Available only after deployment has completed.
EOF
}

help_config-append() {
    cat << EOF
Usage: $0 --config-append=<file>
    Load extra configuration files or answer file.
EOF
}

help_check-deployed() {
    cat << EOF
Usage: $0 --check-deployed
    Report whether the engine has been deployed.
EOF
}

help_check-liveliness() {
    cat << EOF
Usage: $0 --check-liveliness
    Report status of the engine services by checking the liveliness page.
EOF
}

help_connect-storage() {
    cat << EOF
Usage: $0 --connect-storage
    Connect the storage domain.
EOF
}

help_disconnect-storage() {
    cat << EOF
Usage: $0 --disconnect-storage
    Disconnect the storage domain.
EOF
}

help_console() {
    cat << EOF
Usage: $0 --console
    Open the configured serial console.
EOF
}

help_set-maintenance() {
    cat << EOF
Usage: $0 --set-maintenance --mode=<mode>
    Set maintenance status to the specified mode. Valid values are:
    'global', 'local', and 'none'.
    Available only after deployment has completed.
EOF
}

help_set-shared-config() {
    cat << EOF
Usage: $0 --set-shared-config <key> <value> [--type=<type>]
    Set shared storage configuration.
    Valid types are: he_local, he_shared, ha, broker.
    Available only after deployment has completed.

    New values for he_shared (hosted-engine.conf source on the shared storage)
    will be used by all hosts (re)deployed after the configuration change.
    Currently running hosts will still use the old values.
    New values for he_local will be set in the local instance of
    he configuration file on the local host.
EOF
}

help_get-shared-config() {
    cat << EOF
Usage: $0 --get-shared-config <key> [--type=<type>]
    Get shared storage configuration.
    Valid types are: he_local, he_shared, ha, broker.
    Available only after deployment has completed.
EOF
}

help_reinitialize-lockspace() {
    cat << EOF
Usage: $0 --reinitialize-lockspace [--force]
    Reinitialize the sanlock lockspace file. This WIPES all locks.
    Available only in properly deployed cluster in global maintenance mode
    with all HA agents shut down.

    --force  This option overrides the safety checks. Use at your own
             risk DANGEROUS.
EOF
}

help_clean-metadata() {
    cat << EOF
Usage: $0 --clean_metadata [--force-cleanup] [--host-id=<id>]
    Remove host's metadata from the global status database.
    Available only in properly deployed cluster with properly stopped
    agent.

    --force-cleanup  This option overrides the safety checks. Use at your own
                     risk DANGEROUS.

    --host-id=<id>  Specify an explicit host id to clean
EOF
}

help_check-cert() {
    cat << EOF
Usage: $0 --check-cert
    Check the certificate and verify the expiration date.
EOF
}

help_collect() {
    cat << EOF
Usage: $0 --collect
    It collects system status, configuration, logs, and diagnostic 
    data to create a compressed archive file for troubleshooting 
    and diagnosing system issues.
EOF
}

if [ $# -eq 0 ]; then
    rutilvm_main_menu
    exit 0
fi

case "$1" in
	--deploy)
		if [ -n "$2" ]; then
			help_deploy
		else
			hosted-engine --deploy --4 --ansible-extra-vars=he_offline_deployment=true
		fi
		;;
	--deploy-engine)
		if [ -n "$2" ]; then
			help_deploy-engine
		else
			engine_configuration_menu
		fi
		;;
	--deploy-host)
		if [ -n "$2" ]; then
			help_deploy-host
		else
			host_configuration_menu
		fi
		;;
	--vm-start)
		if [ -n "$2" ]; then
			help_vm-start
		else
			hosted-engine --vm-start
		fi
		;;
	--vm-start-paused)
		if [ -n "$2" ]; then
			help_vm-start-paused
		else
			hosted-engine --vm-start-paused
		fi
		;;
	--vm-shutdown)
		if [ -n "$2" ]; then
			help_vm-shutdown
		else
			hosted-engine --vm-shutdown
		fi
		;;	
	--vm-poweroff)
		if [ -n "$2" ]; then
			help_vm-poweroff
		else
			hosted-engine --vm-poweroff
		fi
		;;
	--vm-status)
		if [ -n "$2" ]; then
			help_vm-status
		else
			hosted-engine --vm-status
		fi
		;;
	--add-console-password)
		if [ -n "$2" ]; then
			help_add-console-password
		else
			hosted-engine --add-console-password
		fi
		;;
	 --config-append)
		if [ -n "$2" ]; then
			help_--config-append
		else
			hosted-engine --config-append=
		fi
		;;
	--check-deployed)
		if [ -n "$2" ]; then
			help_check-deployed
		else
			hosted-engine --check-deployed
		fi
		;;
	--check-liveliness)
		if [ -n "$2" ]; then
			help_check-liveliness
		else
			hosted-engine --check-liveliness
		fi
		;;
	--connect-storage)
		if [ -n "$2" ]; then
			help_connect-storage
		else
			hosted-engine --connect-storage
		fi
		;;
	--disconnect-storage)
		if [ -n "$2" ]; then
			help_disconnect-storage
		else
			hosted-engine --disconnect-storage
		fi
		;;
	--console)
		if [ -n "$2" ]; then
			help_console
		else
			hosted-engine --console
		fi
		;;
	--set-maintenance)
		if [ -n "$2" ]; then
			help_set-maintenance
		else
			hosted-engine --set-maintenance
		fi
		;;
	--set-shared-config)
		if [ -n "$2" ]; then
			help_set-shared-config
		else
			hosted-engine --set-shared-config
		fi
		;;
	--get-shared-config)
		if [ -n "$2" ]; then
			help_get-shared-config
		else
			hosted-engine --get-shared-config
		fi
		;;
	--reinitialize-lockspace)
		if [ -n "$2" ]; then
			help_reinitialize-lockspace
		else
			hosted-engine --reinitialize-lockspace
		fi
		;;
	--clean-metadata)
		if [ -n "$2" ]; then
			help_clean-metadata
		else
			hosted-engine --clean-metadata
		fi
		;;
	--check-cert)
		if [ -n "$2" ]; then
			help_check-cert
		else
			if [[ ! -f /etc/ovirt-hosted-engine/hosted-engine.conf ]]; then
				echo "You must run deploy first."
				exit 1
			fi
			task_certificate
		fi
		;;
	--collect)
		if [ -n "$2" ]; then
			help_collect
		else
			echo "Start collecting data from the $(hostname)."
			echo "No changes will be made to system configuration."
			echo
			yes | sosreport -a | grep -Ev "made|version|command|archive|centos|CentOS|representative|policies|sensitive|organization|party|plugin|ENTER|Optionally|Redirecting" | sed '/^$/d'
		fi
		;;
	--help)
		if [ "$2" == "--deploy" ]; then
			help_deploy
		elif [ "$2" == "--deploy-engine" ]; then
			help_deploy-engine
		elif [ "$2" == "--deploy-host" ]; then
			help_deploy-host
		elif [ "$2" == "--vm-start" ]; then
			help_vm-start
		elif [ "$2" == "--vm-start-paused" ]; then
			help_vm-start-paused
		elif [ "$2" == "--vm-shutdown" ]; then
			help_vm-shutdown
		elif [ "$2" == "--vm-poweroff" ]; then
			help_vm-poweroff
		elif [ "$2" == "--vm-status" ]; then
			help_vm-status
		elif [ "$2" == "--dadd-console-password" ]; then
			help_add-console-password
		elif [ "$2" == "--config-append" ]; then
			help_config-append
		elif [ "$2" == "--check-deployed" ]; then
			help_check-deployed
		elif [ "$2" == "--check-liveliness" ]; then
			help_check-liveliness
		elif [ "$2" == "--connect-storage" ]; then
			help_connect-storage
		elif [ "$2" == "--disconnect-storage" ]; then
			help_disconnect-storage
		elif [ "$2" == "--console" ]; then
			help_console
		elif [ "$2" == "--set-maintenance" ]; then
			help_set-maintenance
		elif [ "$2" == "--set-shared-config" ]; then
			help_set-shared-config
		elif [ "$2" == "--get-shared-config" ]; then
			help_get-shared-config
		elif [ "$2" == "--reinitialize-lockspace" ]; then
			help_reinitialize-lockspace
		elif [ "$2" == "--clean-metadata" ]; then
			help_clean-metadata
		elif [ "$2" == "--check-cert" ]; then
			help_check-cert
		elif [ "$2" == "--collect" ]; then
			help_collect
		else
			usage
		fi
		;;
	*)
		usage
		;;
esac