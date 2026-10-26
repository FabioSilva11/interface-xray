# Aquisição de interface Android

Leia quando o alvo for um app Android em aparelho ou emulador acessível. O objetivo é obter evidências da tela renderizada e de sua estrutura exposta, sem confundir isso com recuperação de código, fontes ou projeto original.

## Preparação e alvo

1. Identifique o aparelho, app e tela do pedido. Liste dispositivos com `adb devices -l`; selecione o serial correto em estado `device` e use `-s SERIAL` em todos os comandos seguintes. Com vários alvos sem identificação suficiente, pergunte qual usar.
2. Se a depuração não estiver disponível/autorizada pelo aparelho, explique como habilitar Opções do desenvolvedor e Depuração USB e deixe o usuário aceitar a autorização do dispositivo. Não trate `unauthorized` como conexão pronta. Sem acesso, continue com a referência fornecida depois de validar essa alternativa com o usuário.
3. Registre Android, modelo, versão do app, resolução e densidade lógica efetivas, orientação, idioma, tema, escala de fonte, navegação e rolagem. Considere barras do sistema, teclado e insets. Não altere densidade ou fonte para forçar uma correspondência.
4. Mostre uma captura do alvo no estado inicial e explique qual tela será estudada. Peça confirmação de que o app, tela e estado estão corretos antes da coleta dependente.

Comandos de leitura úteis; substitua `SERIAL` pelo identificador realmente selecionado:

```text
adb devices -l
adb -s SERIAL shell wm size
adb -s SERIAL shell wm density
adb -s SERIAL shell settings get system font_scale
```

Registre também overrides indicados nas respostas. O modelo físico do aparelho e o DPI do arquivo não substituem a densidade lógica efetivamente configurada.

## Captura limpa e hierarquia

O pacote inclui o [utilitário de captura ADB](adb-tool.md), que trata a saída binária no Python, registra metadados e tenta obter a hierarquia complementar. Ele automatiza uma coleta identificada; a seleção do estado da interface, ativação de limites de layout, restauração e revisão com o usuário continuam no procedimento abaixo. Os comandos diretos são uma alternativa quando o script não estiver disponível.

Capture um PNG sem marcadores de diagnóstico. Antes de mudar qualquer opção, registre seu estado anterior; se limites já estavam ativos, desative-os temporariamente para obter a versão limpa e restaure-os no fechamento da coleta.

Escolha um identificador de sessão exclusivo no lugar de `XRAY_SESSION`; crie a pasta de destino local e evite sobrescrever arquivos de outras sessões:

```text
adb -s SERIAL shell screencap -p /sdcard/XRAY_SESSION-clean.png
adb -s SERIAL pull /sdcard/XRAY_SESSION-clean.png ./XRAY_SESSION-clean.png
adb -s SERIAL shell uiautomator dump /sdcard/XRAY_SESSION-ui.xml
adb -s SERIAL pull /sdcard/XRAY_SESSION-ui.xml ./XRAY_SESSION-ui.xml
```

Salvar no dispositivo e usar `pull` evita depender de redirecionamento binário do terminal, que varia entre ambientes. Verifique se o PNG abre e se suas dimensões são consistentes. Em cada estado, associe o XML à captura e ao instante correspondente; mudanças dinâmicas entre as duas operações devem ser registradas.

O XML é uma árvore de acessibilidade disponível, não a árvore completa de desenho. Ele pode conter textos, IDs, estados e limites. Transforme bounds `[esquerda,topo][direita,base]` em bbox, conferindo origem, rotação e correspondência com o PNG antes de sobrepor.

## Mostrar limites de layout e capturar novamente

1. Registre o valor anterior de **Mostrar limites de layout / Show layout bounds** e qualquer outra configuração que pretenda alterar.
2. Ative a opção existente nas Opções do desenvolvedor. Use a interface do aparelho ou uma capacidade específica que seja suportada e verificada naquela versão. Não invente uma chave universal de `settings`, não presuma que um `setprop` funcionou e não force root para ativá-la.
3. Retorne ao app e reproduza a mesma orientação, rolagem, conteúdo e estado da captura limpa. Capture um novo PNG com sufixo `bounds`. Anote diferenças de conteúdo dinâmico em vez de atribuí-las a mudança de layout.
4. Compare os limites visíveis com o XML e a captura limpa. A sobreposição de diagnóstico pode ajudar com caixas, margens e recortes; não garante que cada primitiva de desenho seja exposta nem revela todos os paddings, fontes e efeitos.
5. Faça capturas adicionais dos estados necessários à interface: rolagem, menus, modal, teclado, seleção, erro ou carregamento. Dê a cada estado um ID e registre o caminho para reproduzi-lo. Não execute compras, envios ou outras operações reais apenas para obter um estado visual.
6. Restaure todas as configurações temporárias ao valor anterior, inclusive se houver falha. Verifique a restauração antes de esperar uma resposta do usuário. Restaure também o estado navegável quando viável e informe se uma mudança dinâmica impediu a equivalência exata.
7. Mostre as imagens limpa, instrumentada e anotada lado a lado, com os limites/IDs identificados e a restauração registrada. Pergunte se estão alinhadas e onde há erro; se solicitado, repita a coleta corrigida antes de seguir à medição.

Prefira manter resolução, densidade e fonte intactas. Se um teste específico exigir alterá-las, registre e restaure o valor efetivo anterior; um comando de reset não restaura um override personalizado. Remova apenas temporários criados por esta sessão, depois de verificar as cópias locais.

## Limites por tipo de interface

| Tipo | Evidência possível e limitação |
| --- | --- |
| Views nativas | Hierarquia exposta pode ajudar; screenshot e bounds não determinam todos os estilos. |
| Compose | Semântica pode agrupar ou omitir elementos; não equivale à árvore composable completa. |
| Canvas, jogos e custom views | Várias formas podem aparecer como um único nó; use pixels e medições visuais. |
| WebView | ADB não entrega automaticamente DOM/CSS; inspeção web depende da depuração disponibilizada pelo app. |
| Superfície protegida | Se captura vier bloqueada ou vazia, registre a limitação e use referência fornecida; não declare extração completa. |

Layout Inspector é um recurso opcional quando o app e o ambiente permitem inspeção; não prometa acesso a qualquer APK. Extração de APK, descompilação e instrumentação invasiva não fazem parte desta coleta padrão.

## Entrega desta coleta

- PNGs originais, limpos, com limites e anotações, organizados por estado e revisão.
- XMLs disponíveis e indicação das regiões sem cobertura estrutural.
- Metadados de calibração, lista de configurações alteradas e resultado da restauração.
- Registro das imagens apresentadas, opinião do usuário, correções e aprovação.

Depois da aprovação, retorne à calibração e decomposição do `SKILL.md`. Uma falha no dump não invalida a captura; uma captura bloqueada não prova que a interface não existe.

## Fontes técnicas

- [Android: ADB e screenshots](https://developer.android.com/tools/adb#screencap).
- [Android: opções de desenho e limites de layout](https://developer.android.com/studio/debug/dev-options#drawing).
- [AOSP: implementação do dump UI Automator](https://android.googlesource.com/platform/frameworks/uiautomator/+/dec12c69b4e09679f691050d8fdcab0a5e474258/cmds/uiautomator/src/com/android/commands/uiautomator/DumpCommand.java).
- [Android: semântica do Compose](https://developer.android.com/develop/ui/compose/accessibility/semantics).
- [Chrome: depuração de WebViews](https://developer.chrome.com/docs/devtools/remote-debugging/webviews).
