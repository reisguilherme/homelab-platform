.PHONY: validate kustomize tofu-validate

validate:
	node scripts/validate.mjs

kustomize:
	kubectl kustomize kubernetes/clusters/homelab > /dev/null
	kubectl kustomize kubernetes/platform > /dev/null
	kubectl kustomize kubernetes/spokes-registry > /dev/null
	kubectl kustomize kubernetes/spokes-registry/vaultwarden > /dev/null
	kubectl kustomize kubernetes/templates/spoke-starter > /dev/null

tofu-validate:
	tofu -chdir=infrastructure/proxmox init -backend=false
	tofu -chdir=infrastructure/proxmox validate
