# Análise Matemática de Contornos e Bordas

Módulo opcional que complementa `image_tools.py`. Produz parâmetros e SVG editável; não incorpora a screenshot como bitmap nem trata todas as linhas Canny como UI.

## Instalação e análise

Dentro da pasta da skill:

```text
python -m pip install -r requirements-contour.txt
python scripts/contour_tools.py --help
python scripts/contour_tools.py analyze --image referencia.png --bbox 28,30,145,83 --element-id E01 --output-dir geometria-r01
```

Python 3.10+, Pillow e NumPy. SciPy é um acelerador opcional para vizinhos (`cKDTree`); sem ele, as mesmas distâncias aos pontos são calculadas com NumPy em blocos. Os comandos antigos continuam independentes de NumPy.

O bbox é uma pista do inventário: x,y,largura,altura em pixels da captura, não prova de contorno retangular. `--seed X,Y` escolhe uma região diferente do centro, inclusive uma moldura vazada. Não há classificação semântica automática de toda a tela.

| Opção analyze | Significado |
| --- | --- |
| `--image`, `--bbox`, `--output-dir` | Captura, região e pasta nova; pai da saída deve existir. |
| `--element-id`, `--seed X,Y` | ID e semente em coordenadas da captura completa. |
| `--margin` | Contexto, padrão 10 px; amplie para medir halos. |
| `--fill-tolerance` | Tolerância inicial de cor, padrão 24; ampliações usadas são registradas. |
| `--tolerance` | Erro alvo, padrão 0,6 px, permitido 0,05 a 5; não é garantia para qualquer imagem. |
| `--max-iterations` | Orçamento por candidato, padrão 30, máximo 200. |
| `--loss-weights` | Objeto JSON: contour, color, thickness, regularization. |
| `--exclude-json` | Caixas desconhecidas/ocultas no formato de image_tools annotate. |
| `--detect-markup` | Heurística opt-in de cores diagnósticas puras; pode confundir UI legítima. |
| `--scale` | px da imagem por CSS px, hipótese informada, não calibração automática. |

O recorte com margem tem limite de 2.000 px por lado. Custo depende da área, segmentos e iterações; divida a tela em componentes. Entradas e revisões existentes não são sobrescritas. Orientação EXIF e perfis ICC não são aplicados automaticamente.

## Método e representação

1. Sobel por canal, suavização, supressão não máxima e histerese Canny.
2. Região conectada à semente e fronteiras externas/furos. Se ela não for consistente, raios Canny geram uma alternativa candidata para formas visíveis radialmente da semente. A seleção continua sujeita à revisão humana.
3. Perfis normais à borda refinam posições subpixel. As quatro posições da interpolação bilinear precisam ser confiáveis para estimar cor, faixa e halo.
4. Douglas–Peucker, ajuste ortogonal de retas/interseções, círculos/arcos e Béziers. Modelos simples são tentados antes de acrescentar controles.
5. Chamfer bidirecional e ancoragem refinam vértices numericamente; cores/gradientes usam regressão, espessura variável tem regularização periódica e halo/sombra usa ajuste gaussiano.

Cúbicas: `B(t)=(1-t)^3 P0+3(1-t)^2tP1+3(1-t)t^2P2+t^3P3`. Quadráticas usam três controles. Há retas, polígonos, arcos e caminhos compostos abertos/fechados. Os pontos de controle são estimados, não o código-fonte original.

SDF: distância mínima aos segmentos, negativa dentro e positiva fora. Para curvas, a polilinha de amostragem é uma aproximação explícita, não distância analítica exata à Bézier. Furos compõem campos; cobertura antialias aproxima uma transição de 1 px nos centros dos pixels. `sdf.npy` guarda float32, sem pickle.

Halo: `A*exp(-d^2/(2*sigma^2))` no exterior. Cor, dispersão e intensidade são estimadas separadamente. O SVG usa um filtro gaussiano aproximado. Planos de gradiente RGB sem uma direção comum também precisam de aproximação no SVG; o JSON pode preservar o campo por canal.

Os pesos definem perda composta e regularização local, registradas em `metrics.json/objective`. O ajuste é alternado; não é inversão global conjunta de textura, geometria, alfa e iluminação. Simetria oculta não é imposta como fato.

MSDF não está implementado. A versão atual calcula distâncias em CPU e exporta vetores, sem reamostrar atlas GPU; quinas são preservadas por segmentos. Um alvo que dependa de MSDF exigirá adaptador e validação próprios.

## Arquivos e evidências

| Saída | Conteúdo |
| --- | --- |
| `element.json` | ID, fonte/hash, bbox, recorte, coordenadas crop/image, primitivas, controles, faixas, camadas, efeitos, método, confiança e estado de revisão. |
| `element.svg` | Caminhos M/L/Q/C/A editáveis e preenchimentos/gradientes; furos com evenodd. Sem bitmap incorporado da captura. |
| `metrics.json` | Geometria, aparência, máscaras, condições, objetivo e contexto, separados. |
| `sdf.npy` | Campo assinado; em caminhos abertos, campo não assinado. |
| `source-original.*` | Cópia exata dos bytes originais, preservando formato/metadados. |
| `diagnostics/source_crop_x4.png` | Recorte ampliado 4× por repetição de pixels. |
| `edges_x4.png`, `points_x4.png`, `curves_x4.png` | Bordas, evidências/pontos e curvas/controles, dentro de diagnostics. |
| `render_x4.png` | Render isolado sobre quadriculado. |
| `overlay_x4.png`, `difference_x4.png` | Comparação no recorte, sobre branco; confira também a composição contextual. |
| `full-render.png`, `full-overlay.png`, `full-difference.png` | Tela completa em contexto. Exterior e oclusões são preservados da captura, não reconstruídos independentemente. |
| `unknown-mask.png` | Pixels desconhecidos/excluídos, preservados nas revisões. |

`crop` é relativo ao recorte; `image`, à captura completa. Arcos incluem start_image/end_image e o quadro dos extremos legados. O bbox é fornecido; vértices/controles ajustados são estimados. Cores amostram o composto visível; gradientes e efeitos são estimativas. Confiança é qualitativa e o indicador subpixel mede contraste, não probabilidade calibrada.

Faixas têm caminhos ajustados e larguras por amostra. Sua detecção inicial presume acompanhamento aproximado das normais da base; ornamentos independentes devem ser analisados como elementos separados. O JSON pode alimentar SVG/HTML, Canvas e Android; geradores para todas essas plataformas não estão incluídos.

## Caminhos abertos

```text
python scripts/contour_tools.py trace-open --image referencia.png --bbox 0,0,200,100 --start 20,30 --end 170,65 --stroke-width 2 --output-dir linha-r01
```

As âncoras são fornecidas na captura. O algoritmo segue uma componente Canny conectada e falha se não houver ligação observada, em vez de inventar um atalho. Borda Canny não determina linha central; a espessura informada é proposta. Não há sinal interior/exterior.

Para corrigir uma extração aberta, ajuste âncoras/tolerância/espessura e gere nova saída com trace-open, ou edite o SVG. Não é necessário refazer a coleta. O comando revise opera nas regiões fechadas.

## Revisão paramétrica fechada

Exemplo de correções; use apenas IDs de contorno existentes:

```json
{"colors":{"C0":[40,120,220]},"offsets_px":{"C1":8},"glow":{"enabled":true,"sigma_px":5,"amplitude_alpha":0.6,"color":[255,200,80]}}
```

```text
python scripts/contour_tools.py revise --model geometria-r01/element.json --image referencia.png --overrides correcoes.json --output-dir geometria-r02
```

O hash da origem é conferido; modelos anteriores permanecem intactos. Máscaras, furos e evidências são reutilizados, sem converter regiões ocultas em observadas. `glow:null` remove o efeito. Valores devem ser finitos, sigma positivo, alfa 0–1 e canais 0–255.

Para controlar curvas diretamente, use base_path contínuo e fechado, com coordenadas do recorte:

```json
{"base_path":[{"type":"cubic","control":[[10,60],[30,10],[130,10],[150,60]]},{"type":"line","start":[150,60],"end":[10,60]}]}
```

Tipos aceitos: line, quadratic, cubic, arc. Arcos usam center, radius_px, start_angle_deg e sweep_deg. Alternativamente, base_vertices define um polígono. Não use os dois simultaneamente. Trocar a base preserva faixas por espessura mediana constante; a variação original não é transferida automaticamente para outra parametrização.

## Métricas, máscaras e limitações

Chamfer é a média das distâncias nas duas direções; Hausdorff é a maior distância. Precisão/cobertura usam limiar de 1,5 px. Consistência com a borda detectada não prova que o detector selecionou o componente certo.

MAE RGB e SSIM local de luminância são separados da geometria. SSIM usa janela uniforme 7×7; não é porcentagem de fidelidade. Pixels desconhecidos e vizinhanças contaminadas não entram nas métricas. O contexto informa a população avaliada e não transforma pixels externos copiados em uma nota global.

Prefira captura limpa e exclusões explícitas. A heurística opt-in de cores puras pode apagar UI legítima. Não se recuperam pixels cobertos; fechamentos sob oclusões são hipóteses/desconhecidos.

Transparência sobre cenários 2D/3D, partículas, texturas e iluminação pode não ser identificável em uma captura. Raios não resolvem concavidades arbitrárias. Cor original, alfa e textura não são unicamente recuperáveis. Não há descoberta automática de padrões repetidos entre todos os componentes; reutilize parâmetros de elementos já validados.

ADB/hierarquia e Mostrar limites de layout localizam regiões; não revelam a geometria de Canvas/shaders/OpenGL ES. O usuário precisa validar seleção, curvas e aparência. Nenhum comando aprova a etapa automaticamente.

## Verificar e reproduzir exemplos

Na raiz do repositório:

```text
python -X utf8 -m unittest discover -s tests -v
python tools/validate_package.py
python -X utf8 tools/demo_contours.py --output-dir artifacts/contour-validation-r03
```

A pasta de exemplos deve ser nova. Ela contém referências sintéticas, saídas por caso, summary.json e comparison-gallery.png. A galeria amplifica diferenças 6× só para exibição; métricas e diferenças originais ficam sem amplificação. Os parâmetros verdadeiros não são fornecidos ao extrator, exceto região e exclusões registradas.

Fontes: [Canny/OpenCV](https://docs.opencv.org/4.12.0/d7/de1/tutorial_js_canny.html), [mínimos quadrados/SciPy](https://docs.scipy.org/doc/scipy/tutorial/optimize.html), [MSDF](https://github.com/Chlumsky/msdfgen).
