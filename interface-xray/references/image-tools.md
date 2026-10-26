# Ferramentas locais para imagens

Para chanfros, curvas, arcos, bordas compostas e revisão paramétrica, use o módulo opcional de [análise matemática de contornos](contour-tools.md). Os comandos abaixo mantêm contrato e dependências anteriores.

O utilitário [image_tools.py](../scripts/image_tools.py) mede arquivos raster locais com Pillow. Não usa rede, OCR, geração de imagens nem serviços externos. As entradas são abertas somente para leitura. Execute os exemplos a partir da pasta que contém `interface-xray/`; se a skill estiver instalada em outro local, ajuste o caminho do script.

## Dependências

- Python 3.10 ou superior.
- Pillow na faixa `>=10,<13`, conforme `requirements.txt`. Se ainda não estiver disponível, execute `python -m pip install -r requirements.txt` a partir da pasta da skill, respeitando a política de instalação local.
- Os testes usam `unittest`, incluído no Python.

Consulte a ajuda:

```powershell
python interface-xray/scripts/image_tools.py --help
python interface-xray/scripts/image_tools.py inspect --help
python interface-xray/scripts/image_tools.py annotate --help
python interface-xray/scripts/image_tools.py compare --help
```

O sucesso retorna JSON com indentação e acentos em UTF-8 no stdout, com código de saída `0`. Erros de entrada, arquivo ou escrita retornam `{"error": "mensagem"}` no stderr, com código `2`. A ajuda usa texto. Mensagens de erro não devem ser tratadas como medições.

## Inspecionar e amostrar pixels nativos

```powershell
python interface-xray/scripts/image_tools.py inspect referencia.png
python interface-xray/scripts/image_tools.py inspect referencia.png --point 72,1500 --point 540,1600
```

`inspect` retorna caminho absoluto, SHA-256 dos bytes do arquivo, `size: [largura, altura]`, modo e formato nativos, bandas, presença de canal/transparência, número de quadros, orientação EXIF e presença/hash do perfil ICC. `has_transparency` indica que o formato expõe transparência, sem afirmar que há pixels efetivamente translúcidos.

Cada `--point X,Y` consulta `Image.getpixel` no raster original, sem mudar o modo, a escala ou a orientação. A origem `(0,0)` fica no canto superior esquerdo. `X` e `Y` são inteiros; coordenadas negativas, fora da imagem ou fracionárias são rejeitadas. Use a sintaxe sem espaços.

Exemplo de trecho para uma imagem RGBA:

```json
{
  "size": [1080, 1920],
  "mode": "RGBA",
  "units": "px_imagem",
  "points": [
    {"x": 72, "y": 1500, "pixel": [12, 34, 56, 255]}
  ]
}
```

O valor em `pixel` segue o modo declarado: RGB/RGBA são listas de canais, `L` retorna intensidade e `P` retorna índice de paleta, que não é uma cor RGB. A inspeção não aplica perfil ICC, composição de transparência ou correção EXIF. O SHA-256 identifica os bytes do arquivo; não é uma nota visual. Os valores do exemplo são ilustrativos, não medições de uma imagem fornecida pelo usuário.

## Anotar uma cópia com caixas e IDs

Crie um arquivo `caixas.json` em UTF-8 com este formato:

```json
{
  "units": "px_imagem",
  "boxes": [
    {"id": "E01", "x": 72, "y": 1500, "width": 936, "height": 144},
    {"id": "E02", "x": 72, "y": 1200, "width": 300, "height": 100}
  ]
}
```

As caixas do exemplo exigem uma imagem que comporte suas coordenadas. Execute:

```powershell
python interface-xray/scripts/image_tools.py annotate --image referencia.png --boxes caixas.json --output referencia-anotada-r01.png
```

`--boxes` recebe o **caminho de um arquivo JSON**, não JSON inline. O objeto deve declarar `units: "px_imagem"` e uma lista `boxes` não vazia. Cada caixa exige:

| Campo | Regra |
| --- | --- |
| `id` | Único e sensível a maiúsculas; começa com letra ASCII, até 64 caracteres; demais caracteres são letras ASCII, números, `_`, `-` ou `.`. |
| `x`, `y` | Inteiros não negativos no raster original. |
| `width`, `height` | Inteiros positivos; não aceita booleanos ou decimais. |
| Limites | `x + width <= largura` e `y + height <= altura` da imagem. |

As regiões usam intervalos `[x, x+width)` e `[y, y+height)`: uma caixa de 1×1 em `(largura-1, altura-1)` é válida. A borda de um pixel é desenhada dentro desse intervalo. Os rótulos ficam acima das caixas quando houver espaço; em imagens pequenas, podem sobrepor regiões ou ficar recortados pelo limite do raster. Não use a imagem anotada para medir novamente as cores originais.

A saída é um novo PNG RGBA, nas dimensões nativas, com bordas e IDs vermelhos. O original e o JSON de caixas são preservados. A cópia diagnóstica não aplica nem conserva tags de orientação EXIF ou perfis ICC; isso evita uma transformação adicional das coordenadas pelo visualizador. Guarde o original com seus metadados como evidência.

O arquivo de saída precisa terminar em `.png`, ter pasta pai existente e ainda não existir. Qualquer saída existente é rejeitada, inclusive se for uma das entradas ou um link simbólico. Use um nome por revisão, como `referencia-anotada-r02.png`.

## Comparar dois rasters

```powershell
python interface-xray/scripts/image_tools.py compare --reference referencia.png --actual resultado.png --output-dir comparacao-r01 --threshold 0
```

`--threshold` é obrigatório, inteiro de `0` a `255`. As duas imagens devem ter exatamente a mesma largura e altura. O comando falha para dimensões distintas; não recorta, redimensiona, realinha nem corrige orientação. A pasta pai deve existir, e `--output-dir` deve indicar um diretório **novo**. Não aponte para uma pasta de revisão já criada.

O comando produz:

| Arquivo | Conteúdo |
| --- | --- |
| `overlay.png` | Média dos canais das duas imagens, peso 0,5 para cada uma, com arredondamento de 8 bits do Pillow. |
| `difference.png` | Diferença absoluta dos canais RGB; preto significa igualdade após as conversões declaradas. Sem amplificação e sem máscara de limiar. |
| `metrics.json` | Identificação/hash das entradas, dimensões, MAE RGB, MAE por canal, contagem/fração de pixels diferentes, limiar, condições e caminhos das saídas. |

As transparências de ambas as entradas são **compostas sobre branco RGB `(255,255,255)`** por `Image.alpha_composite`, em RGBA de 8 bits, e então convertidas para RGB. Pixels RGB ocultos por alpha zero não influenciam o resultado; diferenças só de transparência podem desaparecer se o composto visível ficar igual.

As métricas são definidas assim, com `N = largura × altura`:

```text
MAE_RGB = soma, para todos os pixels e canais RGB, de |referência - atual| / (3 × N)
pixel_diferente = máximo(|dif_R|, |dif_G|, |dif_B|) > threshold
different_pixels = contagem dos pixels que atendem à regra acima
different_fraction = different_pixels / N
```

A desigualdade é estrita: diferença máxima igual ao limiar não conta. O MAE considera todos os canais e pixels, independentemente do limiar. `different_fraction` varia de `0` a `1` e é uma fração de divergência de pixels sob essa regra; não é porcentagem de fidelidade nem qualidade perceptual. O utilitário não calcula SSIM.

Exemplo verificável: em imagens RGB de 2×1, referência preta e atual com pixels `(10,20,30)` e `(0,0,0)`, o MAE é `10`; com limiar `20`, há `1` pixel diferente de `2`, fração `0.5`. Com limiar `30`, nenhum pixel conta, embora o MAE continue `10`.

## Condições e limites de interpretação

- A unidade é sempre `px_imagem`. Não há conversão automática para CSS px, dp, sp ou pt.
- Apenas o primeiro quadro (`frame_index: 0`) é inspecionado/anotado/comparado, inclusive em GIF, TIFF ou outros arquivos com vários quadros. A inspeção registra `frame_count`.
- Nenhum comando aplica orientação EXIF. Prepare entradas que representem a mesma orientação do raster; a visualização automática de alguns programas pode girar uma foto.
- A comparação usa conversão de modo do Pillow para canais RGB de 8 bits. Perfis ICC são identificados, mas não aplicados; os valores são códigos RGB, sem linearização de luz. Diferenças de perfil, alta profundidade, CMYK, HDR, gama e rasterização podem exigir preparação separada e documentada. Não interprete igualdade dos códigos como igualdade colorimétrica universal.
- As dimensões precisam coincidir, mas isso não comprova viewport, rolagem, zoom, escala, conteúdo, fonte ou estado equivalentes. Confira essas condições antes da comparação. Não compare a referência original com uma cópia que contenha anotações.
- Uma média global pode esconder um erro localizado. Examine `overlay.png` e `difference.png` por região e complemente com o inventário de medidas.
- Os comandos carregam rasters em memória. Permanecem ativas as proteções do Pillow para imagens excessivamente grandes; avisos de tamanho são tratados como erro, sem desativar esses limites.
- Não há substituição de arquivos. Em falha de disco/permissão durante a escrita, podem restar saídas parciais no diretório recém-criado; confira o erro e escolha um novo nome para repetir. Não trate uma revisão parcial como validada.

## APIs e verificação local

O módulo também expõe funções importáveis que retornam dicionários:

```python
inspect_image(image_path, points=())
annotate_image(image_path, boxes_path, output_path)
compare_images(reference_path, actual_path, output_dir, *, threshold)
```

Entradas inválidas e falhas de imagem/escrita são reportadas por `ImageToolError`, derivada de `ValueError`. A CLI transforma esses erros em JSON amigável.

Na pasta do repositório, execute os testes comportamentais com imagens sintéticas temporárias:

```powershell
python -m unittest discover -s tests -p test_image_tools.py -v
```

Os testes verificam pixels reais, hashes, dimensões, caixas válidas/inválidas, preservação das entradas, bloqueio de sobrescrita, composição alpha, limiar, fórmulas e comandos completos. Eles não dependem de imagens do usuário nem de rede. A aprovação visual exigida pela skill continua sendo uma decisão humana; gerar métricas não aprova uma etapa automaticamente.
