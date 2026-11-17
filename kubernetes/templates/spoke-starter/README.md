# Spoke Starter ("Spoke Factory")

Use este diretório como molde oficial para criar um novo Spoke no ecossistema **HomeServer**.

## Passos para Onboarding de um Novo Spoke

1. Crie o repositório `homelab-<nome>` na raiz do workspace com `AGENTS.md`, `README.md`, `.gitignore`, `.sops.yaml` e `scripts/validate.mjs`.
2. Copie os arquivos de `kubernetes/templates/spoke-starter/` para `homelab-<nome>/kubernetes/` e substitua `spoke-example` / `example-app` pelo nome do seu Spoke.
3. Caso o Spoke exponha ferramentas MCP para o `homelab-hermes`, adicione uma regra `NetworkPolicy` liberando apenas a porta do endpoint MCP a partir do namespace `spoke-hermes`.
4. Criptografe segredos em `secrets/<nome>.sops.yaml` usando `sops -e` (a partir de `secret.sops.yaml.example`).
5. Valide com `kubectl kustomize kubernetes` e registre o `GitRepository` + `Kustomization` em `homelab-platform/kubernetes/spokes-registry/<nome>.yaml`.
