resource "proxmox_virtual_environment_backup_job" "daily_vms" {
  id       = "homelab-daily-vzdump"
  enabled  = true
  node_id  = var.pve_node
  storage  = var.backup_datastore
  schedule = "04:00"
  mode     = "snapshot"
  compress = "zstd"

  vmid = [
    tostring(proxmox_virtual_environment_vm.hub.vm_id),
    tostring(proxmox_virtual_environment_vm.k3s.vm_id),
  ]

  prune_backups = {
    keep-daily  = 7
    keep-weekly = 4
  }

  notes_template = "{{guestname}} automated Hub & Spoke backup"
}
