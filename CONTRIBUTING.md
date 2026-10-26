# Desenvolvimento e verificação

## Preparar o ambiente

Use Python 3.10+ e, na raiz do repositório:

```text
python -m pip install -r requirements-dev.txt
```

Pillow é necessário para os utilitários/testes de imagem. PyYAML é usado na validação do manifesto da skill. O utilitário ADB usa apenas a biblioteca padrão, mas a coleta real exige ADB e um dispositivo autorizado.

## Verificar

```text
python -m unittest discover -s tests -v
python tools/validate_package.py
```

Os testes de imagem usam referências sintéticas temporárias. Os de ADB simulam a fronteira externa; não contatam dispositivos. O validador confere manifesto, referências Markdown locais, fences e sintaxe Python.

Ao alterar comportamento, inclua um teste que detecte o problema antes da implementação. Preserve rejeição de sobrescrita, origem das medidas, limitações e aprovações por etapa. Uma documentação que promete um resultado deve apontar a ferramenta responsável ou declarar a dependência do agente/ambiente.

## Gerar pacote

```text
python tools/build_release.py --version 1.0.0
```

O comando valida o projeto e cria o ZIP da pasta instalável e `SHA256SUMS` em `dist/`. A geração é determinística para os mesmos arquivos e recusa sobrescrita. Use outro diretório de saída em builds repetidos. O pacote contém a skill, manual, referências e utilitários; o código de desenvolvimento e os testes permanecem no repositório.

Não inclua capturas de clientes, dumps de dispositivos, HARs, cookies ou credenciais em contribuições. Exemplos devem usar dados sintéticos ou materiais que possam ser distribuídos, identificados como tal.

## Revisão

Confira tanto a suíte quanto a fidelidade do manual ao comportamento real. Exercite cenários de escala desconhecida, XML indisponível, origem web não localizada, recurso privado e rejeição de uma etapa pelo usuário. Não transforme resultados simulados em alegações de teste real.
