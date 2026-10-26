# Origem e cópia offline de uma interface web

Leia para referências web, com ou sem URL. A unidade de trabalho é a interface/rota e seus estados incluídos no pedido, não o site inteiro.

## Localizar e confirmar a origem

1. Se a URL foi fornecida, abra-a e compare a rota com a referência. Uma homepage do mesmo domínio não comprova que aquela interface foi encontrada.
2. Sem URL, pesquise pistas públicas visíveis: marca, textos distintivos, título, produto e composição. Combine pistas e use busca visual/reversa quando disponível e adequada; não envie dados pessoais da captura como consultas.
3. Registre candidatos, correspondências e divergências. Diferencie **candidata**, **correspondência forte** e **origem não localizada**. Encontrar a fotografia de fundo ou um template semelhante não identifica automaticamente o site da interface.
4. Mostre a referência e capturas reais dos melhores candidatos lado a lado. Indique a região que corresponde e a que diverge. Pergunte se o usuário reconhece a origem e onde a correspondência está errada. Aguarde sua confirmação antes de assumir um candidato como alvo da cópia.
5. Limite a busca inicial a duas rodadas de pistas distintas e até três candidatos plausíveis, salvo orçamento diferente do usuário. Se não houver correspondência confirmada, mostre o resultado e a referência que será usada; peça confirmação da alternativa e continue a recriação baseada na imagem. Registre a origem como desconhecida, sem inventar HTML/CSS original.

Uma confirmação do usuário identifica o alvo desejado; ela não prova autoria histórica nem que a versão atual é a mesma da captura. Se o site mudou, preserve a referência como critério visual e registre a divergência.

## Observar e delimitar a interface

Registre URL/rota, viewport, escala, idioma, tema, estado, rolagem e interações incluídas. Capture a tela antes da coleta e mostre o recorte exato que será reproduzido. Peça confirmação do escopo visual.

Na rota acessível, observe DOM depois da renderização, caixas e estilos relevantes. Inclua pseudo-elementos, variáveis CSS, media queries, fontes efetivamente usadas e recursos de rede. HTML de resposta sozinho pode não conter a interface de uma SPA; valores de estilos computados sozinhos não preservam toda a lógica responsiva.

Se houver suporte, relacione nós DOM e recursos aos IDs do inventário visual. Registre componentes em Shadow DOM, iframes, canvas, vídeo ou WebGL e as limitações de acesso/exportação. Para conteúdo que não possa ser extraído como estrutura, identifique uma captura representativa ou reconstrução local como tal.

## Baixar apenas o necessário

1. Crie uma pasta de saída exclusiva, separada dos originais de referência. Não faça espelhamento recursivo de páginas do site. Links externos não ampliam automaticamente o escopo.
2. Salve o conteúdo renderizado necessário e as dependências que sustentam a interface/estados selecionados: CSS, imagens, ícones, sprites SVG, fontes e scripts estritamente necessários. Preserve regras de layout e relações estruturais.
3. Resolva o fechamento dessas dependências: `@import`, `url()`, backgrounds, máscaras, `srcset`/`picture`, `@font-face`, recursos referidos por SVG e módulos/chunks exigidos pelos estados incluídos. Considere recursos de CDN mesmo quando estiverem em outro domínio.
4. Converta referências de renderização em caminhos locais. Para URLs temporárias `blob:`, dados carregados em runtime e recursos produzidos por código, salve uma representação local quando viável ou reconstrua a parte necessária, registrando a diferença. Não trate copiar uma URL temporária como arquivar o asset.
5. Em SPA, escolha uma captura estática da interface ou uma implementação local mínima para os estados necessários. Reutilizar o bundle original só é útil quando suas dependências forem conhecidas e puderem funcionar localmente. Não dependa do backend original para renderizar a cópia.
6. Mostre a primeira cópia local, suas imagens/assets e a referência lado a lado. Explique o que foi obtido diretamente e o que exigiu reconstrução. Peça a opinião e corrija a aquisição antes de podar ou tomar essa versão como base aprovada.

Baixar arquivos públicos e observar a rota faz parte deste fluxo solicitado; não adicione uma aprovação global extra para cada arquivo. As confirmações exigidas são de resultado visual por etapa. Login indisponível ou recurso privado deve seguir o tratamento de substituições abaixo, sem tentar contornar a restrição.

## Limpar sem quebrar a interface

- Remova da cópia local páginas fora de escopo, rastreamento, analytics, integrações e recursos comprovadamente sem função nos estados incluídos. Se um terceiro desenha conteúdo visível, preserve sua contribuição visual com uma versão local apropriada, quando necessária ao pedido.
- Preserve assets compartilhados realmente usados, fontes, variáveis, keyframes, regras responsivas e estados como foco, hover, menus e modais. Preserve os avisos de licença/atribuição que acompanham recursos mantidos; acesso público não informa sozinho a licença.
- Use cobertura de CSS/JS como evidência parcial: “não usado nesta visita” não significa irrelevante em todos os estados. Não recorte bundles por intervalos arbitrários. Remova uma dependência por vez quando houver dúvida e confira o resultado.
- Faça a limpeza na cópia produzida. Não apague arquivos do projeto do usuário ou evidências originais só porque não aparecem no primeiro viewport.
- Mostre antes/depois da limpeza com capturas comparáveis e resumo do que foi removido. Peça confirmação da equivalência visual. Se o usuário apontar perda de estilo/estado, recupere a dependência ou reconstrua a parte, capture novamente e repita a revisão.

## Links, recursos públicos e substituições

Classifique recursos pela forma real de acesso. Um endereço em domínio público pode exigir sessão, assinatura temporária, cookie ou token; não o declare público estável apenas porque abriu na sessão autenticada.

| Situação | Tratamento |
| --- | --- |
| CSS, imagem ou fonte pública necessária à aparência | Baixar e servir localmente para a versão offline; registrar a origem. |
| Link de navegação público fora da interface copiada | Pode permanecer externo; registrar que abrir o destino exige internet. |
| Link de navegação privado | Informar a restrição e usar uma alternativa pública verificada que cumpra função compatível, com identificação da substituição. |
| Asset privado/indisponível | Informar e usar asset público equivalente quanto a função, composição e proporção, ou um recurso local representativo; mostrar a prévia e registrar a perda de fidelidade. |
| Ação ligada a endpoint privado | Reproduzir o estado visual com dados locais/simulação identificada ou uma tela pública apropriada; não enviar operações ao serviço original nem simular sucesso real. |
| Sem alternativa pública externa verificável | Não inventar URL. Informar a ausência e oferecer uma página local explicativa, acessível na cópia, para revisão do usuário. |

Substituir autenticação ou pagamento por uma homepage genérica não preserva a função. Mostre o destino original indisponível de forma descritiva e o destino proposto, explique a diferença e peça confirmação. Ao corrigir uma substituição, mantenha o histórico e recapture a região afetada. Não inclua cookies, credenciais ou tokens no pacote; sanitize URLs sensíveis do manifesto.

## Manifesto e teste offline

Mantenha um manifesto com origem, caminho local, tipo, componente que usa o recurso, condição de acesso, status da coleta e motivo de inclusão/remoção/substituição. Use estados claros, como `local`, `externo-publico`, `substituido`, `indisponivel` e `removido`. Registre autoria/licença quando informadas, sem deduzi-las do acesso público.

Para declarar **offline**, sirva a cópia por servidor local, abra diretamente a rota de destino e confira os estados incluídos em um contexto sem cache prévio, bloqueando conexões externas e permitindo o servidor local. Verifique CSS, imagens, fontes e scripts; a cache do site original ou seu Service Worker não pode mascarar dependências. Não use `file://` como única prova de funcionamento.

Links públicos externos podem permanecer: o desenho da interface continua offline, mas visitar seus destinos exige rede. Se um recurso remoto ainda for indispensável à renderização ou aos estados incluídos, rotule o resultado como **híbrido** e informe a pendência; não o chame de offline completo.

Mostre a referência, a cópia limpa e a cópia com rede externa bloqueada, com as condições de cada captura. Informe recursos ausentes e substituições. Peça confirmação visual final; repita a etapa afetada quando houver desalinhamento.

Entregue pasta local executável, instrução curta de abertura, manifesto, imagens de progresso/revisões e limitações. Retorne ao fluxo de medição, layout e validação do `SKILL.md`, mantendo os checkpoints de usuário.

## Fontes técnicas

- [Chrome DevTools: estilos aplicados e computados](https://developer.chrome.com/docs/devtools/css/reference).
- [Chrome DevTools: cobertura de CSS/JavaScript](https://developer.chrome.com/docs/devtools/coverage).
- [Chrome DevTools: captura de requisições e exportação sanitizada](https://developer.chrome.com/docs/devtools/network/reference).
