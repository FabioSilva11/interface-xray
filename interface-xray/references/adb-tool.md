# Utilitário de captura ADB

`scripts/adb_capture.py` coleta uma tela Android com Python 3.10 ou posterior, usando apenas a biblioteca padrão. É um coletor executável: quando chamado com ADB disponível e um aparelho autorizado, executa os comandos descritos abaixo. Os testes entregues usam ADB **simulado**, sem conexão a dispositivo; a integração com um aparelho real ainda precisa ser validada no ambiente de uso.

Leia também [aquisição Android](android-acquisition.md). A execução do script não substitui os checkpoints visuais, a aprovação da tela nem a restauração de alterações feitas manualmente.

## Preparar e selecionar o aparelho

Instale Android SDK Platform Tools e disponibilize `adb` no PATH, ou passe o executável em `--adb`. Habilite a Depuração USB no aparelho e aceite a autorização no próprio dispositivo. Liste os alvos:

```text
adb devices -l
```

Copie o serial completo do alvo correto. O coletor exige correspondência exata e estado `device`; `unauthorized`, `offline`, serial ausente e serial duplicado interrompem a coleta. Cada comando direcionado inclui `-s SERIAL`.

Não inicie a coleta dependente enquanto o usuário não tiver visto e confirmado uma imagem do app, tela e estado iniciais. Essa primeira imagem pode ser obtida com o recurso de captura do próprio aparelho. Registre a identificação do app e sua versão, modelo/Android, idioma, tema, orientação, navegação, teclado, rolagem e insets no registro da sessão. O utilitário não preenche esses detalhes automaticamente.

## Executar

A partir da pasta que contém `interface-xray`, substitua `SERIAL` pelo alvo selecionado. A pasta pai `coletas` deve existir; o diretório final precisa ser **novo** em cada execução:

```text
python interface-xray/scripts/adb_capture.py --serial SERIAL --output-dir coletas/tela01-clean-r01 --label clean
```

Exemplo com caminho explícito do ADB e limite de 45 segundos por comando:

```text
python interface-xray/scripts/adb_capture.py --serial SERIAL --output-dir coletas/tela01-bounds-r01 --label bounds --adb "C:/Android/platform-tools/adb.exe" --timeout 45
```

`--skip-hierarchy` dispensa o XML quando só a captura e a calibração são desejadas. `--timeout` aceita segundos positivos e finitos; vale para **cada** comando, inclusive a tentativa de limpeza, e não para a sessão inteira. Não use credenciais como argumento. O script não solicita senhas nem registra variáveis de ambiente.

A CLI usa UTF-8 em stdout e stderr quando os streams oferecem reconfiguração, inclusive no Windows com redirecionamento. Isso permite exibir caminhos Unicode sem interromper uma coleta já concluída. Streams fornecidos pelo chamador permanecem abertos.

| Opção | Significado |
| --- | --- |
| `--serial SERIAL` | Obrigatório; serial exato em estado `device`. |
| `--output-dir NOVO_DIRETORIO` | Obrigatório; nunca reutiliza uma saída existente, mesmo vazia. |
| `--label clean\|bounds` | Obrigatório; rótulo de arquivo escolhido pelo operador. |
| `--adb CAMINHO` | Executável ADB; padrão `adb`. |
| `--skip-hierarchy` | Não executa dump, pull nem limpeza remota. |
| `--timeout SEGUNDOS` | Padrão 30; tempo máximo de cada comando. |

O rótulo `bounds` **não verifica nem ativa** Mostrar limites de layout. `clean` também não prova que a sobreposição está desativada. `capture.json` declara `diagnostics.layout_bounds.verified: false` e `label_only: true` em ambos os casos.

## O que é coletado

1. `adb devices -l` para validar o serial e o estado.
2. Leituras `wm size`, `wm density` e `settings get system font_scale`. São registrados valores físicos, overrides presentes e valores efetivos. O script nunca altera resolução, densidade ou fonte.
3. `exec-out screencap -p`, lido como **bytes** de subprocesso e salvo diretamente. Não usa shell, pipes do terminal nem redirecionamento binário. Antes de salvar o PNG, valida assinatura, IHDR, dimensões positivas, estrutura dos chunks, CRCs e IEND.
4. Opcionalmente, `uiautomator dump /sdcard/xray-UUID.xml`, seguido de `pull` para um temporário local exclusivo. O XML deve ser válido e ter raiz `hierarchy`; declarações de entidades/DOCTYPE e arquivos acima de 32 MiB são recusados. O arquivo final só é criado após validação.
5. Em `finally`, tenta remover **somente** `/sdcard/xray-UUID.xml`, o temporário criado para aquela sessão. Não enumera o armazenamento e não usa curingas, exclusão recursiva, reset, root ou instalação de APK. Também remove seu temporário XML local.

Uma saída completa contém:

```text
tela01-clean-r01/
  clean.png
  hierarchy.xml
  capture.json
```

Na coleta instrumentada, o nome da imagem é `bounds.png`. O JSON inclui serial, UUID da sessão, rótulo, datas UTC, calibração, dimensões e SHA-256 dos arquivos, situação da hierarquia/limpeza e proveniência dos comandos. Não copia o inventário de todos os aparelhos, stderr, ambiente ou conteúdo textual dos nós para os metadados. PNG e XML ainda podem mostrar os dados pessoais presentes na própria tela; selecione um estado adequado e revise os arquivos antes de compartilhá-los.

PNG e XML são capturados em sequência, com horários separados. Não são uma transação atômica: animação, relógio, conteúdo remoto ou rolagem podem mudar entre as duas operações. Registre essas diferenças na sessão e repita se necessário.

## Mostrar limites de layout, fotos e restauração

O coletor não automatiza configurações do aparelho. Siga esta sequência manual, mesmo que a opção já esteja habilitada:

1. Registre o estado anterior de **Mostrar limites de layout / Show layout bounds** com uma foto ou captura da tela de Opções do desenvolvedor. Guarde o valor anterior e essa evidência junto à sessão.
2. Se a opção estava ativa, desative-a temporariamente para a captura limpa. Volte ao app com o estado inicial confirmado. Execute a coleta `--label clean` em uma pasta nova.
3. **Checkpoint com imagem:** restaure qualquer opção temporariamente alterada para a captura limpa antes de aguardar resposta. Depois apresente o PNG limpo ao usuário e confirme app, tela, conteúdo, rolagem, orientação e ausência de marcações de diagnóstico antes da comparação dependente. Uma imagem adicional de calibração pode ser necessária se as dimensões diferirem de `wm size`.
4. Ative **Mostrar limites de layout** pela interface das Opções do desenvolvedor. Registre uma foto ou captura da opção ativa. Não invente chave universal de `settings`, não suponha sucesso de `setprop` e não force root. Reproduza o mesmo estado do app e execute `--label bounds` em outra pasta nova.
5. Em um bloco de encerramento equivalente a `finally`, inclusive se o dump ou a captura falhar, restaure o valor anterior da opção e qualquer outra alteração manual. Verifique visualmente a restauração e registre uma foto ou captura da configuração restaurada **antes de esperar nova resposta do usuário**. Volte ao estado navegável anterior quando viável. Um reset não restaura um override personalizado; não altere densidade ou fonte para tentar igualar referências.
6. **Checkpoint de comparação:** apresente lado a lado as imagens limpa, com limites e anotada, identificando estado, revisão, limites/IDs e resultado da restauração. Pergunte onde há divergências e registre a resposta. Corrija e repita a coleta se necessário; só depois siga para calibração e decomposição da skill.

As fotos e imagens desses checkpoints são evidências produzidas no ambiente real. Os testes offline não produzem nem representam fotos de um aparelho. O utilitário salva a captura original, mas não desenha anotações, não apresenta imagens ao usuário e não registra aprovação automaticamente. Essas etapas permanecem no fluxo da skill.

## Resultado e falhas

| Código de saída | Resultado |
| --- | --- |
| `0` | Coleta completa dentro do escopo solicitado; XML pode ter sido omitido explicitamente. Revise avisos e imagens. |
| `1` | Falha essencial: seleção, calibração, PNG ou gravação. A saída pode conter arquivos incompletos da sessão; preserve-os para diagnóstico e use outra pasta ao repetir. |
| `2` | Coleta parcial com PNG válido e JSON: hierarquia indisponível ou falha de limpeza remota. Erros de sintaxe dos argumentos também usam `2`, conforme o argparse. |

Falha de dump, pull, XML inválido ou tempo limite na hierarquia mantém o PNG e gera aviso explícito com `status: partial`. Se a limpeza remota falhar, o JSON indica o caminho temporário exato; quando a conexão voltar, remova somente esse arquivo, depois de revisar a evidência local. O programa nunca amplia a limpeza para outros arquivos.

Tempo limite na captura interrompe a aquisição sem aceitar um PNG ou JSON como coleta concluída. A mensagem indica verificar conexão/estado e, se necessário, aumentar `--timeout`. Se o ADB não for encontrado, informe o executável por `--adb`.

A validação PNG é estrutural; não faz decodificação completa dos pixels nem detecta tela protegida, preta, desfocada ou alvo incorreto. Abra e revise a imagem. A hierarquia é acessibilidade exposta, não árvore completa de desenho, e pode ter cobertura limitada em Compose, Canvas, jogos e WebView. O script não recupera fontes, estilos, código, DOM ou projeto original.

## Verificação offline

Na raiz deste pacote de trabalho:

```text
python -m unittest discover -s tests -p test_adb_capture.py -v
```

Os testes substituem apenas a fronteira externa `subprocess.run` do ADB. Criação de arquivos, processamento de saídas, validação PNG/XML, proveniência, estado parcial e preservação de dados executam a lógica real. São cobertos seleção exata, `unauthorized`/`offline`, imagem inválida/truncada/CRC incorreto, sucesso, falhas de hierarquia e limpeza restrita, timeout e recusa de saída já existente. Essa verificação não requer ADB instalado e não comprova a integração com um aparelho físico ou emulador.
