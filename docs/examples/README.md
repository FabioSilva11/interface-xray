# Evidências da versão 1.1.0

As imagens da galeria são referências sintéticas produzidas por `tools/demo_contours.py`, não fotografias de um app real. Os parâmetros verdadeiros são usados para avaliação, não fornecidos ao extrator além da região e de exclusões registradas.

Reprodução na raiz do repositório:

```text
python -m pip install -r requirements-dev.txt
python -X utf8 -m unittest discover -s tests -v
python -X utf8 tools/demo_contours.py --output-dir artifacts/contour-validation-nova
```

Use uma saída nova. O gerador preserva as revisões anteriores, escreve referências/JSON/SVG/diagnósticos por caso e cria summary.json e comparison-gallery.png. As diferenças da galeria são amplificadas 6×, mas os arquivos e métricas originais não.

Resultados da suíte local em Python 3.14, comparados com os parâmetros sintéticos conhecidos:

| Caso | Original | Recuperado / erro |
| --- | --- | --- |
| Retângulo chanfrado | Oito vértices conhecidos | Maior erro de vértice: 0,286 px |
| Polígono assimétrico | Cinco vértices conhecidos | Maior erro de vértice: 0,280 px |
| Bézier composta | Curva sintética conhecida | Distância máxima (Hausdorff): 0,891 px |
| Anel concêntrico | Raio interno 52 px; borda 8 px | Raio 52,10 px; borda 8,00 px |
| Bordas duplas | Deslocamentos 8 e 12 px | 8,00 e 12,00 px |
| Brilho | Sigma 5 px | Sigma 5,17 px |
| Oclusão | Dois cantos visíveis conhecidos | Maior erro visível: 0,171 px; parte oculta desconhecida |
| Fundo texturizado | Caixa conhecida | Maior erro de caixa: 1,92 px; textura/alfa não recuperados exatamente |

Esses resultados se aplicam aos casos e condições da suíte. Não são uma porcentagem universal de fidelidade nem garantia para screenshots arbitrárias. As métricas de ajuste às bordas detectadas também não comprovam que o detector escolheu a UI correta.

A suíte inclui ainda espessura variável, furo transparente, marcações contaminadas, caminhos abertos, revisões consecutivas de arcos, preservação de máscaras, gradientes diagonais e não sobrescrita. A composição em tela completa copia regiões externas da captura; não é reconstrução independente da tela inteira.

Limitações restantes: MSDF GPU não implementado; sem adaptadores Canvas/Android completos; extração radial limitada em concavidades; reconstrução de textura, transparência e conteúdo oculto não é única; sombras e exportação SVG de certos gradientes são estimativas.
