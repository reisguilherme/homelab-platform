locals {
  gateway_ip = split("/", var.guest_gateway_cidr)[0]
}

resource "proxmox_virtual_environment_vm" "hub" {
  name        = "homelab-hub"
  description = "Camada 1 HUB: Tailscale, CoreDNS, Traefik, Authelia SSO, Homepage e Observabilidade"
  node_name   = var.pve_node
  vm_id       = 100
  on_boot     = true
  tags        = ["hub", "platform", "opentofu"]

  startup {
    order      = 10
    up_delay   = 15
    down_delay = 15
  }

  agent {
    enabled = true
  }

  cpu {
    cores = 2
    type  = "host"
  }

  memory {
    dedicated = 2560
    floating  = 0
  }

  scsi_hardware = "virtio-scsi-single"

  disk {
    datastore_id = var.primary_vm_datastore
    file_id      = var.ubuntu_cloud_image_id
    interface    = "scsi0"
    size         = 32
    iothread     = true
    discard      = "on"
    ssd          = true
    backup       = true
  }

  network_device {
    bridge   = var.guest_bridge
    model    = "virtio"
    firewall = true
  }

  initialization {
    datastore_id = var.primary_vm_datastore
    ip_config {
      ipv4 {
        address = var.hub_ip_cidr
        gateway = local.gateway_ip
      }
    }
    dns {
      servers = ["1.1.1.1", "9.9.9.9"]
    }
    user_account {
      username = "ubuntu"
      keys     = [var.operator_ssh_public_key]
    }
  }
}

resource "proxmox_virtual_environment_vm" "k3s" {
  name        = "homelab-k3s"
  description = "Camada 2 SPOKES: Cluster K3s single-node + FluxCD + 18 TB USB + Intel QuickSync"
  node_name   = var.pve_node
  vm_id       = 200
  on_boot     = true
  machine     = "q35"
  tags        = ["k3s", "spokes", "opentofu"]

  startup {
    order      = 20
    up_delay   = 20
    down_delay = 30
  }

  agent {
    enabled = true
  }

  cpu {
    cores = 6
    type  = "host"
  }

  memory {
    dedicated = 10240
    floating  = 0
  }

  scsi_hardware = "virtio-scsi-single"

  # System, K3s containerd, and fast SQLite/SSD appdata PVCs
  disk {
    datastore_id = var.primary_vm_datastore
    file_id      = var.ubuntu_cloud_image_id
    interface    = "scsi0"
    size         = 120
    iothread     = true
    discard      = "on"
    ssd          = true
    backup       = true
  }

  # Dedicated NVMe scratch disk for Jellyfin transcode (excluded from vzdump)
  disk {
    datastore_id = var.primary_vm_datastore
    interface    = "scsi1"
    size         = 48
    iothread     = true
    discard      = "on"
    ssd          = true
    backup       = false
  }

  # 18 TB USB HDD exclusive passthrough to K3s VM
  usb {
    mapping = var.media_usb_mapping_id
    usb3    = true
  }

  # Intel UHD QuickSync iGPU passthrough
  hostpci {
    device  = "hostpci0"
    mapping = var.igpu_pci_mapping_id
    pcie    = true
    rombar  = true
  }

  network_device {
    bridge   = var.guest_bridge
    model    = "virtio"
    firewall = true
  }

  initialization {
    datastore_id = var.primary_vm_datastore
    ip_config {
      ipv4 {
        address = var.k3s_ip_cidr
        gateway = local.gateway_ip
      }
    }
    dns {
      servers = [split("/", var.hub_ip_cidr)[0], "1.1.1.1"]
    }
    user_account {
      username = "ubuntu"
      keys     = [var.operator_ssh_public_key]
    }
  }

  depends_on = [proxmox_virtual_environment_vm.hub]
}
