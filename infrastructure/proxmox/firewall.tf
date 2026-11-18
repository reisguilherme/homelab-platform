locals {
  hub_ip = split("/", var.hub_ip_cidr)[0]
  k3s_ip = split("/", var.k3s_ip_cidr)[0]
}

resource "proxmox_virtual_environment_cluster_firewall" "cluster" {
  enabled       = true
  ebtables      = true
  input_policy  = "DROP"
  output_policy = "ACCEPT"

  log_ratelimit {
    enabled = true
    burst   = 10
    rate    = "5/second"
  }
}

resource "proxmox_virtual_environment_firewall_rules" "host" {
  node_name = var.pve_node

  dynamic "rule" {
    for_each = var.lan_management_cidrs
    content {
      type    = "in"
      action  = "ACCEPT"
      comment = "Allow management SSH & Proxmox UI from authorized CIDRs"
      source  = rule.value
      proto   = "tcp"
      dport   = "22,8006"
      enabled = true
    }
  }

  dynamic "rule" {
    for_each = var.lan_tv_cidrs
    content {
      type    = "in"
      action  = "ACCEPT"
      comment = "Allow LAN smart TVs to reach Hub Jellyfin HTTP listener"
      source  = rule.value
      proto   = "tcp"
      dport   = "8096"
      enabled = true
    }
  }

  rule {
    type    = "in"
    action  = "ACCEPT"
    comment = "Allow Hub pve-exporter and Traefik proxy to Proxmox API"
    source  = local.hub_ip
    proto   = "tcp"
    dport   = "8006"
    enabled = true
  }

  depends_on = [proxmox_virtual_environment_cluster_firewall.cluster]
}

resource "proxmox_virtual_environment_firewall_options" "hub" {
  node_name     = var.pve_node
  vm_id         = proxmox_virtual_environment_vm.hub.vm_id
  enabled       = true
  dhcp          = false
  ipfilter      = true
  macfilter     = true
  ndp           = false
  radv          = false
  input_policy  = "DROP"
  output_policy = "ACCEPT"
}

resource "proxmox_virtual_environment_firewall_rules" "hub" {
  node_name = var.pve_node
  vm_id     = proxmox_virtual_environment_vm.hub.vm_id

  rule {
    type    = "in"
    action  = "ACCEPT"
    comment = "SSH from Proxmox gateway or LAN management"
    source  = local.gateway_ip
    proto   = "tcp"
    dport   = "22"
    enabled = true
  }

  rule {
    type    = "in"
    action  = "ACCEPT"
    comment = "LAN TV Jellyfin proxy port forwarded from Proxmox host"
    proto   = "tcp"
    dport   = "8096"
    enabled = true
  }

  rule {
    type    = "in"
    action  = "ACCEPT"
    comment = "Tailscale WireGuard UDP ingress"
    proto   = "udp"
    dport   = "41641"
    enabled = true
  }

  rule {
    type    = "in"
    action  = "ACCEPT"
    comment = "HTTPS ingress to Hub Traefik"
    proto   = "tcp"
    dport   = "443"
    enabled = true
  }

  rule {
    type    = "in"
    action  = "ACCEPT"
    comment = "K3s Promtail logs (Loki 3100), Prometheus (9090), and Split-DNS (53) from VM 200"
    source  = local.k3s_ip
    proto   = "tcp"
    dport   = "53,3100,9090"
    enabled = true
  }

  rule {
    type    = "in"
    action  = "ACCEPT"
    comment = "K3s Split-DNS UDP from VM 200"
    source  = local.k3s_ip
    proto   = "udp"
    dport   = "53"
    enabled = true
  }
}

resource "proxmox_virtual_environment_firewall_options" "k3s" {
  node_name     = var.pve_node
  vm_id         = proxmox_virtual_environment_vm.k3s.vm_id
  enabled       = true
  dhcp          = false
  ipfilter      = true
  macfilter     = true
  ndp           = false
  radv          = false
  input_policy  = "DROP"
  output_policy = "ACCEPT"
}

resource "proxmox_virtual_environment_firewall_rules" "k3s" {
  node_name = var.pve_node
  vm_id     = proxmox_virtual_environment_vm.k3s.vm_id

  rule {
    type    = "in"
    action  = "ACCEPT"
    comment = "SSH from Proxmox gateway"
    source  = local.gateway_ip
    proto   = "tcp"
    dport   = "22"
    enabled = true
  }

  rule {
    type    = "in"
    action  = "ACCEPT"
    comment = "Hub Traefik ingress and Prometheus scraping into K3s"
    source  = local.hub_ip
    proto   = "tcp"
    dport   = "80,443,6443,9100,30080,30096"
    enabled = true
  }

  rule {
    type    = "in"
    action  = "ACCEPT"
    comment = "qBittorrent BitTorrent peers (TCP/UDP 6881)"
    proto   = "tcp"
    dport   = "6881"
    enabled = true
  }

  rule {
    type    = "in"
    action  = "ACCEPT"
    comment = "qBittorrent BitTorrent peers (UDP 6881)"
    proto   = "udp"
    dport   = "6881"
    enabled = true
  }
}

resource "proxmox_virtual_environment_firewall_ipset" "hub_net0" {
  node_name = var.pve_node
  vm_id     = proxmox_virtual_environment_vm.hub.vm_id
  name      = "ipfilter-net0"
  comment   = "Authorized IPv4 source for VM 100 net0"

  cidr {
    name    = "${local.hub_ip}/32"
    comment = "homelab-hub static IPv4"
  }
}

resource "proxmox_virtual_environment_firewall_ipset" "k3s_net0" {
  node_name = var.pve_node
  vm_id     = proxmox_virtual_environment_vm.k3s.vm_id
  name      = "ipfilter-net0"
  comment   = "Authorized IPv4 source for VM 200 net0"

  cidr {
    name    = "${local.k3s_ip}/32"
    comment = "homelab-k3s static IPv4"
  }
}
