bmdmpv — mpv com saída Blackmagic HDMI
=====================================

Implementação de ``--vo=decklink`` e ``--ao=decklink`` para Linux, desenvolvida e testada
com uma Intensity Pro 4K, Desktop Video 16.4a1 e DeckLink SDK 16.0.
O código está em ``mpv/``, copiado de ``/home/paulo/mpv-master/``.

Uso imediato
------------

O executável já foi compilado nesta máquina. Feche o Resolve ou qualquer
aplicativo que esteja usando a placa e execute em um terminal normal::

    cd /home/paulo/bmdmpv
    ./mpv-decklink --list-modes
    ./mpv-decklink --vo-decklink-mode=Hp29 /caminho/video.mkv

O launcher usa ``--no-config --vo=decklink --ao=decklink --hwdec=no``.
Vídeo e áudio saem pela HDMI da mesma placa. O áudio é PCM estéreo de 16 bits
a 48 kHz; o mpv faz resampling e downmix de outras taxas e canais.
Use ``--no-audio`` para reproduzir somente vídeo ou ``--ao=pipewire`` para
enviar o áudio à interface padrão do sistema. O build inclui PipeWire e
PulseAudio; o mpv instalado no sistema continua separado.

O modo padrão é 1080p30 (``Hp30``). Escolha a frequência mais próxima do vídeo;
ela não muda automaticamente com o arquivo. O índice padrão da placa é 0;
use ``--vo-decklink-device=N`` para escolher outra.

Modos confirmados nesta Intensity
--------------------------------

=================  =============================
Código             Modo HDMI
=================  =============================
23ps / 24ps        1080p23,976 / 24
Hp25               1080p25
Hp29 / Hp30        1080p29,97 / 30
Hp50               1080p50
Hp59 / Hp60        1080p59,94 / 60
hp50               720p50
hp59 / hp60        720p59,94 / 60
4k23 / 4k24        2160p23,976 / 24
4k25               2160p25
4k29 / 4k30        2160p29,97 / 30
=================  =============================

Os códigos distinguem maiúsculas e minúsculas. O suporte da placa não garante
que o monitor conectado aceite cada modo.

Exemplos::

    ./mpv-decklink --vo-decklink-mode=23ps filme-23976.mkv
    ./mpv-decklink --vo-decklink-mode=4k29 video-uhd-2997.mkv
    ./mpv-decklink --vo-decklink-mode=Hp29 --sub-file=legenda.srt video.mkv
    ./mpv-decklink --vo-decklink-mode=Hp29 --volume=50 video.mkv
    ./mpv-decklink --vo-decklink-mode=Hp29 --no-audio video.mkv

Espaço pausa, setas fazem busca e ``q`` encerra, com foco no terminal.
A saída não abre uma janela de preview no desktop.

Autocompletar no Bash
--------------------

Com o pacote ``bash-completion`` carregado pelo seu shell::

    ./install-completion.sh

O arquivo é instalado no diretório de completions do usuário, sem editar
``.bashrc``. O carregamento ocorre ao pressionar Tab após ``./mpv-decklink``.
Para ativar imediatamente em um terminal que já tenha carregado outro
completer para esse comando::

    source /home/paulo/bmdmpv/completions/mpv-decklink

Exemplos: ``./mpv-decklink --vo-deck<Tab>`` e
``./mpv-decklink --vo-decklink-mode=Hp<Tab>``. Opções são consultadas no
executável invocado; dispositivos e modos são enumerados sem habilitar saída.
Arquivos, diretórios e nomes com espaços usam o completer padrão do Bash.

Escopo desta versão
-------------------

* Saída HDMI progressiva, SDR, UYVY 4:2:2 de 8 bits, BT.709 em faixa limitada.
* Conversão e redimensionamento por CPU, preservando a proporção da imagem.
* Legendas, OSD, pausa, busca, screenshots da saída e liberação da placa.
* Áudio HDMI estéreo PCM 48 kHz/16 bits, com volume/mute por software,
  conversão de taxa, downmix, pausa/retomada e troca de faixas.
* Configuração HDMI temporária: a interface do SDK a restaura ao ser liberada;
  não é chamada ``WriteConfigurationToPreferences``.
* Sem passthrough AC-3/DTS, áudio multicanal nativo, HDR, saída entrelaçada,
  shaders ou preview simultâneo.
  HDR/BT.2020/Dolby Vision são rejeitados; outros gamuts não têm gerenciamento
  colorimétrico completo. Converta material para BT.709 SDR previamente.
* ``DisplayVideoFrameSync`` com temporização do mpv. A precisão de cadência,
  latência e sincronismo de longo prazo ainda precisa ser medida; esta versão
  não é uma implementação de playout agendado/genlock.

Áudio e sincronização
--------------------

Para vídeo na Intensity e áudio na saída padrão do sistema::

    ./mpv-decklink --ao=pipewire --vo-decklink-mode=Hp29 video.mkv

Também é possível usar a interface PulseAudio (incluindo PulseAudio sobre
PipeWire)::

    ./mpv-decklink --ao=pulse --vo-decklink-mode=Hp29 video.mkv

Essas opções mantêm o vídeo na Blackmagic e deixam o servidor de áudio
escolher a saída padrão, sem alterar a configuração global do sistema.
Na sessão testada, essa saída é a Yamaha AG06/AG03. O áudio HDMI da Intensity
não é habilitado quando outro AO é escolhido. ``--ao=decklink`` seleciona
novamente áudio pela placa, que continua sendo o padrão do launcher.
O autocompletar de ``--ao=`` lista os backends disponíveis no build atual.

Para consultar as interfaces e escolher uma explicitamente::

    ./mpv-decklink --audio-device=help
    ./mpv-decklink --ao=pipewire --audio-device='pipewire/NOME_DO_DISPOSITIVO' video.mkv

Use o identificador exato retornado pela listagem. Dispositivos de áudio e
monitores podem ter latências diferentes; ``--audio-delay`` permite ajustar
o sincronismo manualmente se necessário.

Com ``--ao=decklink``, o AO usa a sessão do VO ativo; não precisa selecionar
a placa duas vezes.
Para arquivos só de áudio, crie essa sessão desde o início::

    ./mpv-decklink --force-window=immediate musica.flac

Essa opção mantém uma saída de vídeo ativa na placa; não cria uma janela de
preview no desktop. O comando foi testado com WAV de 44,1 kHz.

Nesse backend, o buffer de áudio comporta até 200 ms. O atraso informado ao mpv inclui
as amostras pendentes e o contador da fila de hardware. Pausar desabilita
somente o áudio e guarda as amostras ainda não reproduzidas; retomar reativa
o áudio. Buscar descarta a fila anterior. O vídeo permanece ativo.

No Desktop Video 16.4 testado, consultar a fila antes da primeira escrita
retornou erro. Além disso, ``FlushBufferedAudioSamples`` não reinicializou
corretamente a contagem da saída síncrona. A implementação trata esses casos
e usa ``DisableAudioOutput`` / ``EnableAudioOutput`` em pausa e busca.
O mecanismo também é reinicializado após a fila drenar, antes de receber
novos dados, incluindo a transição entre arquivos de uma playlist.

O sincronismo reportado pelo mpv foi verificado com material sintético.
Ainda é necessário ouvir e avaliar lip-sync no monitor/receiver HDMI, cujo
processamento também pode adicionar atraso. Para ajuste manual, use a opção
normal do mpv ``--audio-delay``; isso não substitui a medição física do sinal.

Compilação
----------

Ferramentas: C/C++, Meson >= 1.3, Ninja, Python 3 e pkg-config. O mpv exige os
headers do FFmpeg, libass e libplacebo >= 7.360.1. Este Debian 13 oferece
libplacebo 7.349, então foi compilado localmente o commit
``92b5ac6db79f4d680eb656692f7bf51e9606f42a`` (7.374.0).

Para recompilar usando as dependências já preparadas::

    ./build-probe.sh
    ./build-mpv.sh

Para preparar o mesmo ambiente local em Debian 13, com os runtimes instalados
e ferramentas de desenvolvimento disponíveis::

    ./bootstrap-local.sh

Esse script baixa pacotes ``-dev`` e extrai em ``.deps/root``; não usa sudo nem
instala pacotes no sistema. Os pacotes devem corresponder aos runtimes instalados.
Ele também baixa e compila libplacebo em ``.deps/local``. Bibliotecas transitivas
de desenvolvimento podem precisar estar presentes em uma instalação Debian limpa.
O build local de libplacebo usa OpenGL e desativa Vulkan. Não mova nem apague
``.deps/local`` depois da compilação: o binário depende dessa biblioteca local.

O caminho padrão do SDK é o fornecido para este projeto. Para mudar::

    export DECKLINK_SDK_INCLUDE='/outro/caminho/SDK/Linux/include'
    ./build-probe.sh
    meson configure build-mpv -Ddecklink-sdk="$DECKLINK_SDK_INCLUDE"
    ./build-mpv.sh

Em um ambiente com todas as dependências instaladas, também é possível compilar
diretamente com Meson::

    meson setup build-custom mpv -Ddecklink=enabled \
      -Ddecklink-sdk='/caminho/SDK/Linux/include' -Dmanpage-build=disabled
    meson compile -C build-custom
    ./build-custom/mpv --no-config --vo=decklink --ao=decklink --hwdec=no \
      --vo-decklink-mode=Hp29 video.mkv

O SDK permanece externo ao repositório: o build referencia seus headers e
``DeckLinkAPIDispatch.cpp``. Os novos arquivos de integração usam LGPL-2.1-or-later;
consulte também as licenças do mpv e os termos do SDK antes de redistribuir binários.

Testes
------

Testes sem dispositivo::

    python3 tests/run-bridge-tests.py
    meson test -C build-mpv --print-errorlogs

A ponte é testada com interfaces simuladas geradas a partir dos headers reais:
FPS fracionário, seleção de modos, dispositivo ausente, inicialização parcial,
strides diferentes, falhas de acesso ao buffer e balanceamento de referências.
Os testes de áudio cobrem pré-buffer sem iniciar reprodução, escritas parciais
e nulas, retenção das amostras durante pausa, descarte na busca, drenagem,
erros do SDK e encerramento AO/VO nas duas ordens.
Executa AddressSanitizer/UndefinedBehaviorSanitizer. Os 38 testes do mpv passaram.

Testes físicos explícitos (enviam vídeo pela HDMI; requerem FFmpeg e Pillow)::

    python3 tests/test-hardware.py --mode Hp29
    python3 tests/test-hardware.py --mode 4k29
    python3 tests/test-audio-hardware.py

Esses testes passaram nesta máquina em 1080p29,97 e 2160p29,97: abertura,
envio pelo SDK, FPS reportado, proporção 4:3 com barras, pausa, busca exata,
retomada e encerramento. Screenshots com OSD foram inspecionados em
``test-results/hardware-Hp29.png`` e ``test-results/hardware-4k29.png``.
As capturas representam o buffer enviado, não uma captura do sinal HDMI.
A imagem no monitor físico e a fidelidade/cadência ainda exigem avaliação visual.

O teste de áudio envia tons baixos e vídeo em 1080p29,97. Passou para fontes
estéreo 44,1 kHz, mono 32 kHz e 5.1 96 kHz, convertidas para estéreo 48 kHz;
inclui início pausado, pausa/retomada, busca, troca de faixas, volume/mute, EOF
e continuidade de reprodução entre arquivos de uma playlist.
O relatório e os logs ficam em ``test-results/audio-hardware.log``.
Os testes verificam o envio e o estado do player, não capturam o sinal HDMI
nem comprovam auditivamente canais, fidelidade ou lip-sync.

Também foram verificados ``--ao=pipewire`` e ``--ao=pulse`` com vídeo na
Intensity: os fluxos de áudio foram roteados para a saída padrão Yamaha
AG06/AG03. Pausa, busca, retomada e encerramento passaram nos dois backends.
Logs: ``test-results/system-audio-pipewire.log`` e
``test-results/system-audio-pulse.log``. Os 38 testes do mpv passaram após
a habilitação desses backends.

Arquitetura
-----------

``mpv/video/out/vo_decklink.c`` implementa o VO e usa o scaler/OSD do mpv.
``decklink_bridge.cpp`` isola a API C++/COM do SDK atrás de uma interface C,
consulta os modos HDMI suportados e gerencia configuração, frame e buffer.
O acesso à memória segue ``StartAccess`` / ``GetBytes`` / ``EndAccess`` do SDK 16.
O VO fica depois do driver null na lista, portanto não é selecionado automaticamente.

``mpv/audio/out/ao_decklink.c`` negocia PCM com o mpv. A ponte compartilha a
sessão por instância do player, serializa chamadas do AO/VO e mantém o hardware
vivo até ambos liberarem suas referências. A fila espelhada preserva amostras
em escritas parciais e em pausa. O AO também não é selecionado automaticamente;
o launcher o escolhe explicitamente.

``mpv/TOOLS/decklink_probe.cpp`` usa a mesma ponte para listar dispositivos
e modos sem habilitar saída de vídeo. Se nenhum dispositivo aparecer dentro
de um sandbox, execute a ferramenta em um terminal com acesso à placa.

Referências: o manual local ``Blackmagic DeckLink SDK.md`` (seções 2.5.3,
2.5.17 e 3.18) e a documentação oficial:
https://sdk-doc.blackmagicdesign.com/decklink-sdk/
