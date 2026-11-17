output "hub_vm_id" {
  value = proxmox_virtual_environment_vm.hub.vm_id
}

output "hub_ip" {
  value = split("/", var.hub_ip_cidr)[0]
}

output "k3s_vm_id" {
  value = proxmox_virtual_environment_vm.k3s.vm_id
}

output "k3s_ip" {
  value = split("/", var.k3s_ip_cidr)[0]
}
