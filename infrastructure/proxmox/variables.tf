variable "pve_endpoint" {
  description = "HTTPS endpoint of the Proxmox VE API (e.g. https://192.168.1.20:8006/)"
  type        = string
}

variable "pve_api_token" {
  description = "Proxmox API token in format USER@REALM!TOKENID=SECRET"
  type        = string
  sensitive   = true
}

variable "pve_tls_insecure" {
  description = "Skip TLS verification only when using a self-signed PVE certificate before CA trust"
  type        = bool
  default     = false
}

variable "pve_node" {
  description = "Target Proxmox node name"
  type        = string
  default     = "pve01"
}

variable "primary_vm_datastore" {
  description = "Proxmox datastore for new VM disks during zero-risk cutover"
  type        = string
  default     = "nvme-secondary"
}

variable "backup_datastore" {
  description = "Proxmox datastore storing daily vzdump backups"
  type        = string
  default     = "nvme-secondary"
}

variable "ubuntu_cloud_image_id" {
  description = "Proxmox file ID of the Ubuntu 24.04 cloud image (e.g. local:iso/noble-server-cloudimg-amd64.img)"
  type        = string
}

variable "operator_ssh_public_key" {
  description = "SSH public key injected via cloud-init for Ansible and emergency access"
  type        = string
}

variable "guest_bridge" {
  description = "Internal Proxmox bridge shared by Hub and K3s VMs"
  type        = string
  default     = "vmbr1"
}

variable "guest_gateway_cidr" {
  description = "Gateway IPv4/prefix for internal guest subnet"
  type        = string
  default     = "172.28.64.1/24"
}

variable "hub_ip_cidr" {
  description = "Static IPv4/CIDR assigned to VM 100 (homelab-hub)"
  type        = string
  default     = "172.28.64.100/24"
}

variable "k3s_ip_cidr" {
  description = "Static IPv4/CIDR assigned to VM 200 (homelab-k3s)"
  type        = string
  default     = "172.28.64.200/24"
}

variable "lan_management_cidrs" {
  description = "Authorized LAN/Tailscale CIDRs allowed to reach Proxmox SSH/Web UI"
  type        = list(string)
  default     = ["192.168.1.0/24", "100.64.0.0/10"]
}

variable "lan_tv_cidrs" {
  description = "Local home LAN CIDR allowed to reach LAN TV Jellyfin listener on port 8096"
  type        = list(string)
  default     = ["192.168.1.0/24"]
}

variable "media_usb_mapping_id" {
  description = "Proxmox datacenter USB resource mapping ID for the 18 TB media HDD"
  type        = string
  default     = "media-hdd-18tb"
}

variable "igpu_pci_mapping_id" {
  description = "Proxmox datacenter PCI resource mapping ID for Intel UHD QuickSync iGPU"
  type        = string
  default     = "intel-igpu-qsv"
}
