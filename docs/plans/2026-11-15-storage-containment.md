# Plano: detectar falha do hub e conter a playback

Escopo autorizado: primeira entrega de contenção, com QGA e cron existentes,
sem novas units, montagem automática, reparo, alteração de passthrough ou start
de VMs/containers. A recuperação física completa continua pendente.

## Decisões e fronteiras

A plataforma executa probes assíncronos no core e publica autorização temporária
no SSD da playback. Um único incidente persiste no SSD PVE; uma operação de I/O
pendente nunca causa criação de outra. Falha, identidade diferente ou timeout
entram em HOLD. `arm` inicial e `resume` são ações explícitas de readmissão; não
executam start, mas a nova autorização permite a retomada pela restart policy
existente. Paradas manuais de Docker permanecem respeitadas.
O consumidor implementa a recusa/parada quando a autorização vencer.

Lease ASCII, exatamente cinco linhas, em
`/var/lib/homelab-storage/admission/lease` (diretório root 0755, arquivo root 0644):

```text
version=1
state=ready
boot_id=00000000-0000-0000-0000-000000000000
generation=00000000000000000000000000000000
expires_uptime_seconds=12345
```

O consumidor monta o diretório RO e compara boot ID do guest e uptime. HOLD usa
expiry zero. Cada publicação tem sequência persistente e deadline UTC; NTP é
precondição operacional. O helper converte o prazo restante para uptime, com
máximo 45 s. Comando atrasado ou repetido não prolonga autorização.

O core confere mount/UUID/serial lsblk/serial ATA/tamanhos/partição/geração e
faz leitura O_DIRECT de uma fixture de 64 KiB, fora do acervo. Não há fallback
para cache se O_DIRECT falhar. Isso prova uma pequena leitura atual, não todos
os bytes do disco, nem estabilidade elétrica.

## Implementação

- [x] Testes com backend fake: estados, prazo, PID pendente, resposta atrasada,
  identidade, autorização explícita, pausa e falha de publicação.
- [x] Helper guest com perfil estrito root-owned, probe sem escrita de mídia e
  publicação atômica de lease no SSD; fixtures de filesystem temporárias.
- [x] Coordenador stdlib com flock não bloqueante, persistência atômica, QGA
  assíncrono, comandos fixos, resposta limitada e verificação do perfil das VMs.
- [x] Documentar instalação privada, tick/watch/cron, HOLD, retomada explícita e
  limites; executar testes Linux/WSL e lint.

Verificação local: 59 testes focados, 153 testes na suite da plataforma e lint/
formatação aprovados em Python 3.12 no WSL. Esses resultados usam fixtures;
implantação e ensaios no servidor precisam de evidência operacional própria.

`watch --seconds 58` executa ticks curtos a cada 2 s, liberando lock entre eles;
cron existente pode chamá-lo a cada minuto. Probes saudáveis têm intervalo mínimo
de 10 s. Deadlines do probe e da confirmação de lease são 15 s. Todos os comandos
`qm` têm timeout de 8 s.
Um timeout de lançamento sem PID é ambíguo e exige intervenção; não é tratado
como prova de que nada iniciou. Expiração da lease contém também a perda do
coordenador. Nenhuma frequência constitui RTO garantido.

A janela foi ampliada de 50 para 58 s após simulação com custo de 1,5 s por
chamada `qm`: o período anterior podia consumir resultado concluído depois do
deadline, entrando em HOLD. O prazo de 15 s e a lease de 45 s foram preservados.
O início da operação deve acompanhar a passagem para um cron já ativo; um watch
manual curto seguido de espera também pode deixar uma execução expirar.
Ações manuais que encontram flock ocupado retornam 75 e não foram aplicadas;
o operador confirma modo/motivo e estado da autorização antes de prosseguir.

## Aceite e limitações

Testar expiração sintética de autorização sem desligar o HD. Conferir que scans
continuam suspensos, catálogo preservado e mídia RO. Provar containment por esse
ensaio não comprova D-state, perda real de USB, NFSv4 sem referências ou retorno
da fonte. Estados pendentes/ambíguos e pausas não são apagados por `resume`.
Não instalar o recuperador monolítico. Não usar `soft`, unmount forçado/lazy,
fsck corretivo, reboot automático ou scan para simular recuperação.
