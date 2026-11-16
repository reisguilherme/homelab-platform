# Console operacional, discos e recursos

## Objetivo e decisões

O proprietário pediu acessos administrativos uniformes, discos físicos visíveis,
controle dos serviços dentro das VMs e painéis úteis com consumo de RAM explicado.
Autorizou execução e implantação. Depois confirmou que o portal mantém a identidade
atual do Proxmox: essas duas credenciais não serão alteradas. Credenciais dos demais
aplicativos ficam exclusivamente nos destinos privados; contas comuns Jellyfin e
chaves de integração permanecem.

Evoluir o FastAPI/JavaScript e Grafana existentes evita outro painel, agente ou VM.
Um painel adicional de containers duplicaria autenticação, coleta e consumo; trocar
a plataforma inteira atrasaria as correções operacionais. A interface será um console
compacto com visão geral, máquinas, serviços, discos e atividades, usando dados reais.
Não remover isolamento nem diminuir RAM apenas para melhorar um número.

## Contratos e limites

- Discos: API PVE para os dispositivos do host; probe RO no core pelo textfile do
  exporter existente para o HD exclusivo. Cada fonte tem estado e idade; ausente
  nunca significa zero ou saudável. A API privada exige permissão Sys.Audit.
- Runtime: QEMU Guest Agent existente, por identidade humana Proxmox, executa um
  helper de caminho fixo no guest. O navegador envia apenas ID de serviço e ação
  tipada; nunca comandos, caminhos, nomes de containers ou argumentos arbitrários.
  Catálogo local controlado por root permite apenas os projetos implantados.
- Serviços: mostrar estado, tipo de gerenciador, memória observada, destino e ações
  permitidas. Intenção durável e chave idempotente antes de uma ação; resultado
  ambíguo não pode causar reenvio automático. Preservar CSRF, ACL e auditoria.
- Manter guards, mídia RO, manutenção e paradas manuais. Nenhum início automático
  de aplicativos, nenhum reparo/format/mount, nenhuma exclusão de mídia.
- Portal não interrompe seu próprio transporte/autenticação. Ações de containers
  dependentes de storage devem verificar os mounts antes de iniciar/reiniciar.
- RAM: separar memória configurada, residência no host e consumo dentro do guest;
  não somar os três. Otimizações exigem medidas antes/depois e saúde preservada.

## Execução

- [x] Padronizar administradores pelas APIs dos aplicativos, preservar integrações,
  atualizar configuração privada e verificar login/logout em cada serviço.
- [x] Implementar normalizadores de discos, métricas/probe e endpoint privado com
  testes de fonte ausente, dados inválidos, frescor, autorização e não duplicação.
- [x] Implementar helper runtime, transporte QGA e endpoints de serviços; testar
  seleção exata, permissões, reenvio idempotente, estado concorrente e guard storage.
- [x] Reorganizar portal e Grafana; testar navegação, renderização de dados faltantes,
  ações, desktop/mobile e ausência de exposição de credenciais.
- [x] Implantar alterações coordenadas, medir RAM, verificar discos e serviços reais,
  fazer ensaio limitado de ação reversível e preservar as configurações privadas.
- [ ] Atualizar guias e publicar mudanças revisadas na branch refactor.

## Verificação

Python 3.12/Linux, testes com fixtures isoladas; sintaxe JavaScript e ensaio de
navegador. Testes unitários não comprovam hardware: recibos privados registram
inventário real, disponibilidade por HTTPS, ação concluída e medidas antes/depois.
Não armazenar segredos, dados brutos ou identidades físicas reais neste documento.
