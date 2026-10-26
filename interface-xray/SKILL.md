---
name: interface-xray
description: "Use when a user requests an interface X-ray, raio X de interface, screenshot-to-code reconstruction, Android UI cloning via ADB, a route-scoped offline website copy, or a visual fidelity audit with step-by-step user review."
---

# Interface X-Ray

Transforme uma referência visual em uma especificação verificável para recriar a interface com fidelidade. Preserve composição, conteúdo e hierarquia. Separe o que foi medido, o que foi inferido e o que está ausente.

## Escopo e ferramentas

- Se o pedido for análise, entregue o diagnóstico e os materiais visuais; implemente somente quando isso fizer parte do pedido.
- Se o usuário já pediu a recriação, mantenha esse escopo e siga as etapas autorizadas, respeitando a confirmação visual obrigatória de cada etapa descrita abaixo.
- Use as capacidades disponíveis no ambiente: visão, leitura de imagens, amostragem de pixels, OCR, navegador, pesquisa, acesso a assets, ADB e captura da implementação. Não dependa de nomes de ferramentas exclusivos de Codex ou Claude; use integrações disponíveis ou ferramentas locais equivalentes.
- A inspeção visual do modelo produz estimativas. Para afirmar leitura pixel a pixel, execute operações sobre os pixels reais, identifique arquivo e método e delimite as regiões analisadas. Não prometa que todos os pixels foram inspecionados se isso não ocorreu.
- Se não conseguir abrir a referência, solicite uma imagem acessível. Se faltar uma ferramenta de medição, identifique a limitação e diferencie resultados aproximados de medidos.
- Reutilize assets e componentes do projeto quando disponíveis. Faça as perguntas de revisão exigidas nesta skill e solicite outras informações somente quando alterarem materialmente o resultado. Trabalho independente pode continuar enquanto uma resposta está pendente; etapas dependentes aguardam aprovação explícita.

### Utilitários incluídos

Leia a referência correspondente antes de usar um utilitário:

- [Ferramentas de imagem](references/image-tools.md): `scripts/image_tools.py` inspeciona pixels/metadados, anota caixas fornecidas e compara capturas sem redimensionamento ou alinhamento automático. Requer Python 3.10+ e Pillow de `requirements.txt`.
- [Captura Android](references/adb-tool.md): `scripts/adb_capture.py` coleta uma tela, metadados e a hierarquia exposta quando disponível. Requer Python 3.10+, ADB e dispositivo autorizado. Não ativa limites de layout; siga o procedimento de configuração e restauração.
- [Modelo de relatório](references/report-template.md): organiza evidências, inventário, recursos, correções e aprovações. Preencha com resultados reais.

Os scripts preservam entradas e recusam sobrescrever saídas existentes. Use novo nome/diretório a cada revisão. Não confunda marcação automática de caixas fornecidas com detecção automática de componentes. Para instalação, capacidades e solução de problemas, consulte o [manual](MANUAL.md).

## Revisão visual obrigatória em cada etapa

O usuário acompanha a preparação, coleta, medição e recriação com imagens reais e decide se cada resultado está alinhado. Essa revisão faz parte do trabalho, inclusive quando ele já autorizou a implementação inteira.

1. Apresente uma sequência curta de etapas aplicáveis: preparação/origem, coleta, calibração, camadas, geometria, tipografia, limites de layout, cópia offline ou implementação e validação. Identifique a etapa atual, sua revisão e seu estado: em execução, aguardando revisão, em correção ou aprovada. Não agrupe todas as revisões no fim.
2. Ao terminar cada etapa, mostre capturas/fotos reais da referência e do resultado daquela etapa. Para preparação, mostre o alvo e os candidatos de origem; para coleta, capturas limpas e instrumentadas; para medições, referência com caixas, cotas, unidades e legenda. Para implementação, mostre referência e resultado lado a lado e, quando possível, sobreposição/diferenças. Mostre também as prévias de substituições de assets.
3. Diferencie captura original, captura com diagnóstico, anotação sobre a captura e esquema inferido. Preserve imagens sem marcações. Um desenho gerado não serve como prova de uma tela capturada. Tabelas e texto complementam as imagens.
4. Diga o que foi feito, quais regiões observar e quais dúvidas permanecem. Pergunte sempre: **“Esta etapa está alinhada com a referência? Onde você vê algo errado e como deveria ficar?”** Use o mecanismo de perguntas do ambiente, quando disponível, com opções como “Alinhado”, “Precisa corrigir” e “Não tenho certeza”, permitindo comentário livre. No restante dos ambientes, faça a pergunta diretamente.
5. Aguarde resposta explícita antes de avançar para uma etapa dependente. Silêncio, tempo decorrido, uma pergunta do usuário ou aprovação de uma etapa anterior não aprovam a etapa atual. Uma autorização genérica para começar não elimina esses checkpoints.
6. Se o usuário apontar desalinhamento, registre a região/ID e o ajuste solicitado; corrija, repita a captura e a comparação e apresente nova revisão da mesma etapa. Peça confirmação novamente. Se a descrição não localizar o problema, peça a região ou uma descrição curta antes de decidir a correção.
7. Aplique as correções solicitadas dentro do escopo. Se um ajuste for inviável, conflitante ou dependente de informação ausente, explique concretamente e pergunte como proceder, sem ignorar o pedido nem declarar a correção concluída. Se a correção alterar etapas já aprovadas, revalide as afetadas.
8. Salve imagens por etapa e revisão sem sobrescrever as anteriores; mantenha um registro com imagem, observação, pedido de correção e resposta do usuário. Ao final, mostre o que foi aprovado e o que continua pendente.

Se não puder produzir ou exibir imagens reais, informe a limitação e solicite a captura ou o acesso que falta. A aprovação visual dessa etapa fica pendente; não a substitua automaticamente por texto. Na saída do Codex, use prévias ou imagens com caminhos absolutos; em outros ambientes, use anexos/prévias suportados e links de acesso.

Restaure configurações temporárias do dispositivo e encerre instrumentação antes de aguardar a revisão. Aguardar o usuário não é motivo para deixar opções de diagnóstico alteradas.

## Contrato de evidência

Classifique cada medida ou decisão relevante:

| Classe | Significado |
| --- | --- |
| Medido | Obtido do arquivo, de uma ferramenta ou de metadados confirmados; informe o método. |
| Estimado | Inferido da aparência ou ajustado por comparação; informe intervalo e confiança. |
| Proposto | Escolha para implementar algo que a imagem não determina. |
| Desconhecido | Informação indisponível; indique o que permitiria determiná-la. |

Confiança alta, média ou baixa é uma avaliação qualitativa, não uma probabilidade calculada. Não trate precisão decimal como prova de exatidão. Registre a origem dos dados: arquivo, região, escala, ferramenta e hipótese usada.

## 0. Obter a melhor referência disponível

Escolha o caminho e leia somente o guia aplicável:

- **App Android acessível em aparelho/emulador:** siga [aquisição Android via ADB](references/android-acquisition.md) para capturas renderizadas, hierarquia exposta, densidade e versão com limites de layout. Esses dados complementam a imagem; não são uma extração automática do projeto original.
- **Site com URL conhecida:** siga [origem e cópia web por interface](references/web-acquisition.md) para observar a rota, seus estilos e assets e preparar a cópia offline solicitada.
- **Screenshot de site sem URL:** pesquise a origem conforme o guia web. Compare visualmente os candidatos e peça ao usuário confirmação da correspondência. Se a origem não for localizada, siga com a imagem fornecida e as etapas de medição desta skill; não invente um site original.
- **Somente imagem, sem alvo acessível:** preserve a referência e trabalhe com medidas e hipóteses explícitas. Se a imagem parecer web, execute primeiro a busca de origem prevista acima; para Android sem acesso ao aparelho, registre a coleta ADB como indisponível.

Registre origem, arquivos coletados, estado da interface e limitações. Cada resultado da preparação/coleta passa pela revisão visual antes de alimentar as etapas dependentes. Se houver ferramentas como REA, ADB, DevTools ou automação de navegador disponíveis, use as capacidades adequadas, sem torná-las dependências obrigatórias da skill portátil.

## 1. Calibrar a referência

1. Abra a imagem e registre dimensões nativas, formato, transparência e orientação. Preserve o original. Identifique compressão, reamostragem ou baixa resolução que afetem a análise.
2. Delimite a interface útil: separe navegador, moldura do aparelho, barras do sistema e áreas externas. Distinga screenshot de viewport, página inteira, recorte e fotografia de uma tela. Não confunda altura da página com altura da janela.
3. Registre, quando conhecidos: plataforma, viewport lógico, DPR ou densidade lógica, zoom, escala de exportação, recortes, rolagem, tema e escala de texto. O DPI gravado no PNG não comprova a densidade lógica da interface.
4. Use a origem `(0, 0)` no canto superior esquerdo do arquivo original. Se analisar recortes, registre seus offsets e reconverta as coordenadas para o original.
5. Para cada elemento, use `bbox = (x, y, largura, altura)`, com intervalos `[x, x+largura)` e `[y, y+altura)`. Registre separadamente limites do componente, tinta do texto e extensão da sombra. Identifique bordas parcialmente ocultas.

### Unidades e conversões

Pixels do arquivo são a unidade inicial. Unidades lógicas exigem calibração independente.

| Unidade | Regra |
| --- | --- |
| px da imagem | Medida no raster original; pode ter sofrido recorte ou redimensionamento. |
| CSS px | Unidade lógica da web. Não equivale automaticamente a um pixel do arquivo. |
| Android dp | Unidade de layout baseada na densidade lógica configurada. |
| Android sp | Unidade de texto dependente também das configurações de fonte. |
| iOS pt | Ponto lógico da plataforma; não confundir com a unidade CSS `pt`. |

Para uma captura web com escala efetiva confirmada `s` em pixels de imagem por CSS px:

```text
comprimento_css = comprimento_imagem / s
```

Em uma captura não reamostrada que realmente use pixels de dispositivo, `s` pode coincidir com o DPR. Algumas ferramentas exportam diretamente em CSS px. Não multiplique zoom e DPR indiscriminadamente: o DPR informado pode já refletir o zoom.

No Android, antes de processamento adicional da captura:

```text
px_renderizados = dp × density
density = densityDpi / 160
dp = px_imagem / (r × density)
```

`r` é a escala de redimensionamento posterior: tamanho final dividido pelo tamanho renderizado, sendo `1` quando não houve redimensionamento. Use densidade lógica, não PPI físico. Para texto em sp, use as APIs e configurações do ambiente; a escala de fontes pode ser não linear. Não derive sp somente de dp ou DPR.

No iOS, converta pontos apenas com o fator entre o espaço lógico e o raster da captura confirmado. Sem calibração, mantenha px da imagem e proporções; apresente conversões hipotéticas como cenários, nunca como medidas confirmadas.

Se houver escala diferente nos eixos, registre `sx` e `sy` e a deformação. Em fotografias com perspectiva, medidas retificadas são aproximações; preserve a transformação aplicada.

## 2. Decompor em regiões, componentes e camadas

Faça uma leitura da composição inteira, depois de regiões, componentes e detalhes. Use recortes ampliados para bordas, glifos e sombras sem perder sua posição no original.

Atribua IDs estáveis, como `E01`, e organize uma árvore de pais e filhos. Classifique cada região:

- **Geometria simples:** retângulo, círculo, linha, borda, preenchimento ou gradiente reproduzível por primitivas nativas/CSS/SVG.
- **Componente de interface:** botão, campo, card, lista, navegação ou modal; a aparência sugere o papel, mas não comprova comportamento.
- **Texto:** conteúdo editável, separado de imagens quando houver evidência.
- **Asset:** fotografia, textura, ilustração, logotipo ou ícone que exija arquivo próprio.
- **Efeito:** sombra, máscara, blur, transparência, mistura ou sobreposição.
- **Indeterminado:** região que admite múltiplas interpretações; registre as alternativas.

Um retângulo arredondado pode ser um botão, um card ou parte de uma imagem. Use contexto, repetição, alinhamento e evidências dos assets para decidir. Procure componentes dentro de imagens: uma fotografia pode conter a imagem de uma interface, sem que seus controles sejam interativos.

Para separar interface e fundo:

1. Identifique candidatos a fundo contínuo e elementos sobrepostos; registre o que sustenta essa interpretação.
2. Priorize o asset original disponível. Um recorte de screenshot é uma extração do composto visível, não necessariamente o asset original.
3. Separe regiões visíveis, parcialmente cobertas e totalmente ocultas. Se produzir máscaras, diferencie pixels observados de áreas inferidas.
4. Descreva transparência, gradientes de escurecimento, recorte, proporção e posição focal. Cor de pixel composto não revela sozinha cor e opacidade de cada camada.
5. Informe que pixels escondidos por um card opaco não podem ser recuperados exatamente de uma única captura. Qualquer preenchimento ou geração é uma aproximação e deve ser identificado como tal.

Para profundidade, registre relações como `E07 cobre E03`, plano de fundo, superfície e overlay. Estime deslocamento, desfoque, expansão e opacidade das sombras por comparação. Diferencie sombra incorporada no asset de efeito do componente. A imagem não revela distância 3D, elevação nativa ou valor original de `z-index`; proponha uma ordem suficiente considerando os contextos de empilhamento.

## 3. Medir geometria e aparência

Por componente relevante, registre:

- bbox em px da imagem e, se calibrado, na unidade lógica do destino;
- alinhamentos, distâncias às bordas, gaps entre irmãos e relação com o pai;
- tamanho externo, borda, conteúdo e padding inferido, distinguindo essas caixas;
- raio de cada canto, espessura de traço, proporção e recorte;
- preenchimentos, cores, gradientes e efeitos, com método e confiança;
- área visível e possível área de interação, sem deduzir esta última apenas da primeira.

Amostre cores no interior de áreas uniformes, evitando bordas suavizadas. Registre perfil/espaço de cor quando relevante; compressão, transparência e gerenciamento de cores afetam o resultado. Preserve o perfil do original e documente conversões usadas para comparar.

Detecte repetições para propor tokens de espaçamento, cores, raios e tamanhos. Não force uma grade de 4 ou 8 unidades quando ela contradisser a referência. Preserve medições observadas e documente qualquer normalização proposta.

## 4. Estimar texto e tipografia

1. Transcreva o texto; confira OCR contra a imagem, incluindo acentos, números, símbolos e quebras. Marque trechos ilegíveis.
2. Meça caixa de tinta, largura das linhas, alinhamento e distância entre baselines quando observáveis. Altura de glifos não equivale a `font-size`; espaço entre linhas não revela sozinho o `line-height` declarado.
3. Procure fontes fornecidas e estilos existentes. Sem evidência suficiente, indique candidatos de família, peso e estilo com confiança; a aparência não prova uma fonte exata.
4. Estime tamanho nominal renderizando o mesmo texto com candidatos. Compare largura, altura visível, quebras, baseline, kerning e espaçamento entre letras. Registre fallback e eixos de fontes variáveis quando afetarem a comparação.
5. Resolva família, peso, tamanho e largura do contêiner antes de compensar diferenças com tracking ou escala artificial. Espere as fontes carregarem antes de capturar a implementação.

Documente diferenças de rasterização entre sistemas. Texto implementado como texto mantém seleção, acessibilidade e adaptação; texto incorporado em um asset deve ser identificado.

## 5. Definir limites de layout

Converta coordenadas em regras de layout, mantendo separadas regras comprovadas e propostas. Para cada região principal, especifique:

| Propriedade | Decisão a registrar |
| --- | --- |
| Dimensões | Fixa, fluida ou intrínseca; mínimos, máximos e unidade. |
| Ancoragem | Bordas, centro, alinhamento com irmãos e contêiner de referência. |
| Distribuição | Colunas, gaps, alinhamento, quebra e ordem dos elementos. |
| Conteúdo | Padding, largura de texto, crescimento e comportamento com textos longos. |
| Imagens | Proporção, ajuste, posição focal e limites de corte. |
| Overflow | Rolagem, recorte, truncamento e região responsável. |
| Posicionamento | Fluxo, sobreposição, fixo ou sticky, com evidência ou rótulo de hipótese. |
| Adaptação | Safe areas, barras do sistema, teclado e mudança de orientação quando aplicáveis. |

Uma captura isolada não determina breakpoints nem comportamento de rolagem. Com várias capturas, compare relações e mudanças estruturais; um breakpoint pode ser delimitado entre larguras observadas sem que seu valor exato seja conhecido.

Com apenas uma captura, preserve primeiro o viewport de referência e proponha regras para outras larguras identificadas como extrapolação. Prefira layout em fluxo para conteúdo e posicionamento absoluto para sobreposições reais. Não transforme cada coordenada medida em posição absoluta.

## 6. Mostrar o raio X ao usuário

Entregue o diagnóstico nesta ordem, ajustando o volume à complexidade:

1. **Resumo e calibração:** referência, região útil, unidades, escala conhecida e principais incertezas.
2. **Mapa anotado:** referência com IDs e caixas, seguida de vista esquemática das camadas. Diferencie UI, texto, assets e efeitos por cor e legenda. Anotações ficam em uma cópia separada.
3. **Inventário de medidas:** IDs, pais, tipo, bbox, unidade, fonte da medida, classe de evidência e confiança. Separe tabelas de geometria, estilo e tipografia se uma tabela única ficar ilegível.
4. **Mapa de camadas e assets:** ordem de sobreposição, arquivos reutilizáveis, extrações possíveis e regiões ocultas ou indeterminadas.
5. **Contrato de layout:** limites, ancoragens, overflow, comportamento responsivo conhecido e decisões propostas.
6. **Aquisição e cópia local:** quando aplicável, capturas ADB e hierarquia, evidências da origem web, manifesto de arquivos, recursos públicos/privados, substituições e teste offline.
7. **Revisões do usuário:** imagens mostradas em cada etapa, ajustes pedidos, revisões aprovadas e decisões pendentes.
8. **Pendências por impacto:** o que falta, como obter e quanto isso afeta a fidelidade.

Se houver suporte a artefatos, salve o relatório e imagens com nomes claros, como `xray-report.md`, `xray-annotated.png` e `xray-layers.svg`, e apresente links ou prévias. Use subpastas de etapa/revisão para o histórico. Gere somente arquivos úteis ao pedido. Se não conseguir produzir ou exibir imagens necessárias à revisão, entregue o que estiver disponível e mantenha a etapa aguardando evidência visual, conforme o protocolo de confirmação.

### Exemplo de evidência e limite

Referência de 1080 × 1920; bbox informado de botão `(72, 1500, 936, 144)`; escala desconhecida:

- Geometria conhecida: botão de 936 × 144 px da imagem; margens laterais de 72 px, equivalentes a 6,67% da largura.
- Hipótese: se a escala efetiva for 3 pixels de imagem por CSS px, o botão corresponderá a 312 × 48 CSS px. Isso não confirma a medida em dp.
- Layout: margens iguais sustentam centralização, mas não provam margens percentuais. A largura máxima é desconhecida.
- Uma caixa de tinta de 61 px de altura não comprova tamanho nominal de fonte de 61 px, nem de 20,33 após uma divisão hipotética por três.
- Não há porcentagem de fidelidade antes de definir critérios e comparar uma renderização real.

## 7. Quando houver implementação autorizada

Implemente do macro para o micro: estrutura e assets, dimensões e espaçamentos, tipografia, cores, efeitos e detalhes. Preserve componentes e padrões do projeto que permitam reproduzir a referência.

Use elementos semânticos e controles reais, mantendo foco, teclado e estados necessários. Não use a screenshot inteira como fundo para simular uma interface funcional. Preserve ícones e logos com os assets correspondentes; emojis ou símbolos parecidos não comprovam equivalência.

Liste estados visíveis e ausentes: hover, foco, pressionado, selecionado, desabilitado, carregamento, erro e vazio. Estados ausentes são decisões propostas. Avalie contraste, legibilidade, ordem de leitura, áreas de toque, texto ampliado e movimento reduzido; comunique conflitos com a referência sem redesenhá-la silenciosamente.

## 8. Validar a recriação

Se não houver implementação executável ou acesso à captura, marque a validação visual como pendente. Não declare fidelidade validada apenas por revisar o código.

Quando houver captura:

1. Igualar viewport, escala, enquadramento, estado, rolagem, conteúdo e tema. Registrar navegador/sistema, fontes e versões relevantes. Estabilizar animações e dados variáveis.
2. Verificar dimensões e correspondência de coordenadas antes da comparação. Não redimensionar ou deslocar silenciosamente o resultado para esconder erros de layout.
3. Mostrar lado a lado e sobreposição com transparência; produzir imagem de diferenças quando a ferramenta permitir. Comparar regiões e componentes além da imagem inteira.
4. Informar métricas somente quando calculadas: erro de posições e tamanhos, discrepâncias de bordas e texto, MAE de cores ou SSIM, conforme disponíveis. Registrar método, parâmetros, unidades e regiões avaliadas. SSIM não é uma porcentagem de fidelidade.
5. Declarar qualquer máscara de exclusão e sua área; não excluir regiões difíceis para melhorar o resultado. Uma grande fotografia semelhante pode esconder um botão errado na média global.
6. Ordenar desvios por impacto: asset/composição, geometria, tipografia, cor, efeitos e detalhes. Corrigir a maior fonte de erro antes de refinar sombras.

Use tolerâncias do usuário quando fornecidas. Caso contrário, proponha critérios por categoria antes da comparação e registre-os como propostas. Como ponto inicial, em captura calibrada, teste erro geométrico de até 1 unidade lógica em elementos críticos, conteúdo e quebras de texto correspondentes e ausência de cortes indevidos; ajuste a exigência à qualidade da referência e ao ambiente. Sem calibração, expresse a tolerância em px da imagem.

Conclua a etapa de validação quando os critérios definidos forem atendidos e o usuário aprovar as imagens finais. Se um bloqueio impedir avanço ou duas rodadas não melhorarem o mesmo desvio, mostre a comparação, exponha a causa e pergunte a opinião do usuário sobre onde está errado e o que ajustar; não finalize unilateralmente como aprovado. Respeite o orçamento de iterações informado e combine qualquer mudança necessária. Informe resultados por critério e diferenças residuais; não prometa equivalência universal entre plataformas.

## Erros que comprometem o resultado

| Erro | Correção |
| --- | --- |
| Confundir px da captura, CSS px e dp | Calibrar e manter unidades separadas. |
| Apresentar estimativa como leitura pixel a pixel | Informar método e incerteza; medir o raster quando possível. |
| Tratar todo retângulo como componente interativo | Verificar contexto e separar aparência de comportamento. |
| Prometer fundo original atrás de área opaca | Solicitar asset/outra vista ou identificar reconstrução aproximada. |
| Declarar fonte, breakpoint ou elevação exatos sem evidência | Mostrar candidatos, limites e decisões propostas. |
| Dizer que a recriação está fiel sem captura comparável | Entregar evidências da comparação ou marcar validação pendente. |
| Avançar sem mostrar imagens e pedir a opinião do usuário | Apresentar o checkpoint visual e aguardar aprovação da etapa. |
| Ignorar um desalinhamento ou presumir que foi resolvido | Corrigir, recapturar e pedir nova confirmação da mesma etapa. |

## Critério de entrega

O resultado deve permitir que outra pessoa identifique o que recriar, como medir, quais assets usar, como limitar o layout e como conferir o resultado. O usuário deve ter visto imagens do progresso e validado as etapas, incluindo as correções solicitadas. Inclua pendências reais; não invente arquivos, medições, aprovações, testes ou percentuais.
