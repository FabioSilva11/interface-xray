# Interface X-Ray: uso e pontos que faltavam

O arquivo principal está em [interface-xray/SKILL.md](interface-xray/SKILL.md). A versão distribuível inclui [manual completo](interface-xray/MANUAL.md), guias de [coleta Android](interface-xray/references/android-acquisition.md) e [origem/cópia web](interface-xray/references/web-acquisition.md), além de utilitários locais para imagens e captura ADB. A pasta inteira forma a skill portátil.

## Progresso visual e confirmação por etapa

Cada etapa de preparação, coleta, calibração, camadas, geometria, tipografia, layout, cópia/implementação e validação deve mostrar imagens reais do seu resultado e perguntar se está alinhada e onde há erro. O agente aguarda a resposta antes de avançar para uma etapa dependente.

Ao apontar um desalinhamento, o usuário recebe uma nova revisão da mesma etapa, com correção, novas capturas e comparação. A aprovação anterior não cobre alterações posteriores. Um histórico vincula imagens, regiões, solicitações de ajuste e aprovações. Quando a correção afetar outras etapas, elas também são revalidadas.

As imagens devem distinguir captura original, diagnóstico do aparelho, marcações de medição e esquemas inferidos. Sem imagens reais disponíveis, a revisão visual fica pendente; não é substituída silenciosamente por uma explicação textual. Configurações temporárias são restauradas antes de aguardar a resposta do usuário.

## Coleta Android e web

- **Android acessível:** selecionar o dispositivo via ADB, registrar densidade/configuração e capturar a interface limpa, a hierarquia exposta e uma versão com Mostrar limites de layout. Depois, restaurar as configurações anteriores, mostrar os resultados e pedir confirmação. O PNG não é um projeto editável e o XML pode não representar todo o desenho.
- **Site sem URL:** pesquisar pistas públicas do screenshot, comparar candidatos com imagens e pedir confirmação da origem. Se a origem não for encontrada, mostrar essa limitação e validar o uso da referência enviada antes de continuar a recriação.
- **Site localizado:** copiar somente a interface/rota e as dependências necessárias, incluindo CSS, imagens, fontes e comportamento local incluído no pedido. Limpar a cópia com comparação antes/depois, preservando estilos e estados necessários.
- **Links e recursos privados:** informar a restrição, mostrar alternativas públicas adequadas e registrar as substituições. Sem equivalente externo verificável, não inventar URL; apresentar alternativa local explicativa para revisão.
- **Offline verificável:** testar a cópia sem cache do original e com rede externa bloqueada, mantendo acesso ao servidor local. Links públicos de navegação podem continuar externos; recursos remotos indispensáveis ao desenho tornam a entrega híbrida.

## O que foi acrescentado à ideia

1. **Calibração antes de medir.** Pixels de uma imagem não revelam automaticamente CSS px, dp ou pontos do iOS. Densidade lógica, zoom, exportação e redimensionamento podem alterar a relação. Sem essas informações, as medidas permanecem no espaço da imagem.
2. **Rastreabilidade e incerteza.** Cada resultado diferencia medida, estimativa, proposta e informação desconhecida, com fonte e confiança. Isso evita transformar palpites visualmente convincentes em especificações falsas.
3. **Limite da separação de camadas.** Uma captura achatada não contém os pixels escondidos por um componente opaco. Ela também pode não permitir separar opacidade e cor originais. Recuperar o asset original e gerar uma aproximação são resultados diferentes.
4. **Profundidade visual.** Sobreposição, sombra e desfoque permitem descrever planos aparentes. Não determinam distância 3D, elevação nativa ou o valor original de z-index.
5. **Tipografia além do tamanho.** Família, peso, fontes variáveis, fallback, largura do contêiner, quebras, baseline e espaçamento precisam ser conferidos juntos. A altura visível das letras não é o tamanho nominal da fonte.
6. **Regras de layout.** Medir posições não basta: é preciso definir ancoragens, mínimos, máximos, proporções, overflow e comportamento com conteúdo maior. Uma captura não prova breakpoints ou posicionamento fixo.
7. **Estados e acessibilidade.** Hover, foco, carregamento, erro, áreas de toque e texto ampliado não costumam aparecer na referência. A skill registra esses estados como pendências ou propostas para a implementação.
8. **Validação reproduzível.** A recriação precisa ser capturada nas mesmas condições e comparada por região. Uma média global boa pode esconder um texto ou botão errado.
9. **Critério de parada.** Tolerâncias e limites de iteração evitam ajustes infinitos, especialmente quando o problema real é uma fonte ou asset indisponível.
10. **Capacidade real das ferramentas.** O Markdown instrui o agente; não adiciona sozinho um leitor exato de pixels. Sem acesso ao raster e ferramentas adequadas, a análise deve ser apresentada como estimativa.
11. **Origem e aquisição.** A análise não precisa se limitar à screenshot: pode obter evidências Android e recursos da rota web. Correspondências, cobertura e falhas de coleta continuam explícitas.
12. **Revisão acompanhada.** O usuário vê imagens de cada etapa, aponta desalinhamentos e aprova os ajustes antes que decisões dependentes sejam tomadas.

## Usar no Codex e no Claude

O núcleo usa apenas `name`, `description` e instruções Markdown, seguindo o formato Agent Skills. O conteúdo pode ser o mesmo nos dois ambientes; os diretórios de descoberta e as ferramentas disponíveis variam.

Para descoberta local por projeto, copie a pasta completa `interface-xray` para:

| Ambiente | Destino dentro do projeto |
| --- | --- |
| Codex | `.agents/skills/interface-xray/SKILL.md` |
| Claude Code | `.claude/skills/interface-xray/SKILL.md` |

Copie a pasta completa, incluindo `references/`. Não é necessário adicionar campos exclusivos de uma plataforma ao arquivo compartilhado. Mantenha uma versão principal e sincronize as cópias para evitar divergências.

Esses caminhos se referem ao Codex e ao Claude Code locais. No Claude em navegador/Cowork, use o mecanismo de skills oferecido pela conta; ler a pasta local não é garantido. Colar o texto em uma conversa permite usá-lo como instrução, mas não equivale a instalar uma skill descoberta automaticamente.

### Pedido de diagnóstico

> Use a skill interface-xray na imagem anexada. O destino é web, ainda não conheço a escala nem a URL. Pesquise a origem; se não encontrar, siga pela referência. Quero somente o diagnóstico, com imagens do progresso. Em cada etapa, pergunte se está alinhada e onde preciso de correção; aguarde minha resposta.

### Pedido de recriação

> Use a skill interface-xray para recriar a interface neste projeto. Se for Android acessível, obtenha capturas via ADB e limites de layout; se for web sem URL, procure a origem. Se encontrar o site, prepare a cópia offline apenas desta interface, com os recursos necessários e alternativas públicas para os privados. Mostre imagens e peça minha confirmação em cada etapa. Corrija e repita as etapas que eu apontar como desalinhadas.

## Utilitários disponíveis

O pacote inclui [inspeção de pixels, anotações e comparação](interface-xray/references/image-tools.md) e [coleta ADB](interface-xray/references/adb-tool.md). Confira requisitos e comandos no manual. A identificação semântica de componentes, busca da origem e coleta web continuam conduzidas pelo agente. Recortes, máscaras avançadas e identificação exata de fontes não são anunciados como funções automáticas dos scripts.

Para avaliar a skill, use referências com geometria e assets conhecidos e depois casos reais. Inclua capturas sem densidade, fontes indisponíveis, fundos cobertos e versões em diferentes larguras. Confira tanto a precisão das medidas quanto a honestidade sobre o que não pode ser inferido.

## Referências de compatibilidade e unidades

- [Agent Skills: especificação do formato](https://agentskills.io/specification).
- [OpenAI: criação e descoberta de skills no Codex](https://learn.chatgpt.com/docs/build-skills).
- [Anthropic: skills no Claude Code e locais de carregamento](https://code.claude.com/docs/en/skills).
- [Android: densidade lógica, dp e pixels](https://developer.android.com/training/multiscreen/screendensities).
- [Android: limitações de scaledDensity para texto](https://developer.android.com/reference/android/util/DisplayMetrics).
- [Android: captura pelo ADB](https://developer.android.com/tools/adb#screencap).
- [Android: Mostrar limites de layout](https://developer.android.com/studio/debug/dev-options#drawing).
- [Chrome DevTools: cobertura de CSS/JavaScript](https://developer.chrome.com/docs/devtools/coverage).
