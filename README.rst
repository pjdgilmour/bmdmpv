bmdmpv — mpv com saída Blackmagic HDMI
=====================================

Implementação de ``--vo=decklink`` e ``--ao=decklink`` para Linux, desenvolvida e testada
com uma Intensity Pro 4K, Desktop Video 16.4a1 e DeckLink SDK 16.0.
O código está em ``mpv/``, copiado de ``/home/paulo/mpv-master/``.

Pacote Debian
-------------

O pacote em ``dist/bmdmpv_0.1.2-1_amd64.deb`` destina-se ao **Debian 13
(trixie), amd64**. Com o Desktop Video da Blackmagic já instalado::

    sudo apt install ./dist/bmdmpv_0.1.2-1_amd64.deb

Depois, abra **bmdmpv** pelo menu de aplicativos ou execute ``bmdmpv-gui``.
O terminal também oferece ``mpv-decklink`` e seu autocompletar. Não é preciso
compilar nem manter esta pasta para usar o pacote instalado. O aplicativo
usa ``/usr/lib/bmdmpv`` e uma cópia privada de libplacebo; não substitui o mpv
ou as bibliotecas do sistema. Perfis continuam em ``~/.config/bmdmpv``.

Python/Tkinter permanece como GUI. O mpv em C/C++ executa a decodificação e
a saída de áudio/vídeo; migrar a interface para Qt/GTK não é requisito para
empacotamento ou desempenho desse processamento.

As dependências incluem Python/Tk, FFmpeg, bibliotecas detectadas por
``dpkg-shlibdeps`` e ``desktopvideo >= 16.0``. O driver proprietário precisa
ser obtido da Blackmagic separadamente; o pacote não contém driver nem SDK.
Para YouTube, use yt-dlp e um runtime JavaScript compatível, como
Deno >= 2.3. A instalação de yt-dlp é recomendada pelo pacote; o runtime deve estar
disponível conforme a documentação do YouTube abaixo. Cookies, arquivos de
mídia e configurações pessoais não fazem parte do pacote.

Para gerar novamente, após compilar os binários locais::

    python3 scripts/build-deb.py
    python3 tests/test-deb.py

O empacotador exige ``dpkg-dev``, ``binutils``, ``desktop-file-utils`` e
``patchelf`` (também aceita ``PATCHELF=/caminho/para/patchelf`` ou a cópia
local em ``.deps/patchelf/usr/bin/patchelf``). Não usa sudo nem instala pacotes.
Produz o ``.deb``, um arquivo ``_sources.tar.xz`` com os fontes modificados
do projeto/mpv e libplacebo, e ``_SHA256SUMS``. O SDK permanece externo à
compilação. ``--version 0.1.3-1`` permite gerar uma versão nova.

``test-deb.py`` extrai o pacote em um diretório temporário e verifica caminhos,
bibliotecas, lançadores, checksums e reprodução com saídas nulas. A instalação
pode ser simulada com ``apt-get --simulate install ./dist/bmdmpv_0.1.2-1_amd64.deb``.
Outras versões de Debian/Ubuntu precisam de compilação própria para suas
versões de FFmpeg e bibliotecas. Para remover: ``sudo apt remove bmdmpv``;
seus perfis e mídias são preservados.

Interface gráfica
-----------------

Para abrir o player no desktop::

    cd /home/paulo/bmdmpv
    ./bmdmpv-gui

Também é possível abrir um arquivo pela linha de comando, sem iniciar sua
reprodução automaticamente::

    ./bmdmpv-gui /caminho/video.mkv

1. Clique em **Adicionar arquivos**. A GUI usa ``ffprobe`` para consultar resolução,
   proporção, taxa de quadros, duração e presença de áudio.
2. Selecione a placa e a resolução de saída. **Automático · priorizar FPS**
   procura entre os modos HDMI progressivos realmente enumerados pelo SDK.
   Há opções para forçar 720p, 1080p ou 2160p e um **Modo manual** para escolher
   exatamente a resolução e frequência desejadas.
3. Em **Enviar áudio para**, escolha HDMI da Blackmagic, a saída padrão do
   sistema (PipeWire ou PulseAudio), uma interface específica ou **Sem áudio**.
4. Clique em **Reproduzir**. Os controles permitem pausar, buscar na linha do
   tempo, avançar/recuar 10 segundos, ajustar volume, silenciar, repetir e
   aplicar atraso do áudio. Um atraso positivo retarda o áudio; negativo,
   retarda o vídeo. **Parar** libera a placa e permite trocar arquivo e saídas.

A detecção automática distingue 23,976 de 24 fps e 29,97 de 30 fps. Procura
a mesma frequência, múltiplos inteiros e, por último, a frequência mais próxima,
escolhendo uma resolução adequada. **Preferir 50/60 Hz na HDMI**, habilitado
por padrão, troca uma frequência exata baixa por 50/59,94/60 Hz quando houver
um múltiplo inteiro na mesma resolução: 1080p25 → 1080p50, 1080p29,97 →
1080p59,94 e 1080p30 → 1080p60. Os quadros são repetidos, mantendo duração,
velocidade e áudio originais. Essa preferência não força redução de resolução
nem altera o **Modo manual**. Desmarque-a para priorizar a frequência nativa.
Ela é salva nos perfis; perfis anteriores mantêm a seleção nativa até você
ativar a opção e salvar novamente.

Por exemplo, 720p29,97 sugere 1080p59,94 com a preferência ativa; UHD60
sugere 1080p60 nesta Intensity. Ao forçar 720p para um arquivo de 29,97 fps,
seleciona 720p59,94. Material entrelaçado identificado
pelo ``ffprobe`` ativa o desentrelaçamento do mpv e considera a taxa de campos.
Arquivos com taxa variável usam a taxa média informada pelo ``ffprobe``;
a sugestão não garante reprodução sem repetição/descarte de quadros.
O monitor conectado ainda precisa aceitar o modo selecionado: o SDK enumera
os modos da placa, sem validar os modos da tela. A consulta EDID pelo SDK não
está disponível na Intensity/driver desta máquina. Se houver áudio mas a tela
ficar sem sinal, experimente um modo HDMI que o monitor aceite.

O **Enquadramento** oferece ajustar com barras preservando a imagem,
preencher com corte das bordas e esticar sem preservar a proporção.
Up/downscale é feito pelo mpv na CPU. As `especificações da Intensity Pro 4K
<https://www.blackmagicdesign.com/uk/developer/products/capture-and-playback/techspecs/W-DLK-25>`_
descrevem o downscale durante reprodução como software e o upscale para
captura. A GUI não ativa conversões de hardware do SDK nem altera
permanentemente a configuração da placa.

Durante a reprodução, o painel **Áudio** oferece **Trilha de áudio** e
**Legenda**, com idioma, título e codec quando informados pelo arquivo.
Os seletores mostram a seleção real do mpv e permitem trocar as trilhas
durante reprodução ou pausa, sem reiniciar o player. **Sem áudio** desativa
a trilha de áudio; **Desativada** desliga a legenda. A rota **Enviar áudio
para** continua sendo a escolha da interface de saída.

As listas ficam disponíveis depois que o mpv abre o arquivo e são limpas
ao parar ou trocar de item. Arquivos sem legendas mostram **Sem legendas
disponíveis**. IDs de trilha pertencem ao arquivo atual e não são salvos
nos perfis. Legendas selecionadas são desenhadas na imagem enviada à HDMI.
No YouTube, o mpv também recebe as legendas publicadas disponibilizadas pelo
yt-dlp; os seletores apresentam apenas as trilhas que o player abriu. A
extração atual continua escolhendo uma faixa de áudio do YouTube, sem
importar todas as dublagens nem solicitar legendas geradas automaticamente.

**Atualizar saídas** consulta novamente a placa e as interfaces de áudio.
Ao terminar o último arquivo sem repetição, o player mantém o último quadro
e oferece **Reiniciar**;
fechar a janela encerra seu processo de reprodução e libera a placa.
**Diagnóstico** permite copiar o comando e salvar o log da última sessão
depois de parar. ``Ctrl+O`` adiciona arquivos e ``Esc`` para a reprodução.

A GUI usa Python 3.10+ com Tkinter (``python3-tk`` no Debian), ``ffprobe``
e os binários locais já compilados. Essas dependências já estão disponíveis
nesta máquina. Não requer um servidor web ou instalação de bibliotecas via pip.
A imagem é enviada à HDMI; não há preview de vídeo no desktop. As limitações SDR/8 bits
do backend continuam válidas; HDR/BT.2020/Dolby Vision identificados na
análise são bloqueados antes de iniciar a saída.

Playlists e perfis
-----------------

**Adicionar arquivos** permite selecionar vários arquivos de uma vez e os
acrescenta à lista atual. O primeiro item é analisado, mas só começa ao clicar
em **Reproduzir**. O botão **Playlist (N)** abre a lista: remova itens, altere
a ordem com **Subir/Descer**, ou dê duplo clique para reproduzir um item.
Pare a reprodução para editar a lista. **Anterior/Próximo** navegam entre os
itens; durante a reprodução, iniciam o item escolhido. Com o player parado,
apenas o selecionam para análise.

Ao final de cada arquivo, a GUI passa ao próximo e recalcula o modo HDMI
quando a resolução está em automático. A saída é encerrada e reaberta por
item, inclusive para alterar a frequência: há uma interrupção entre arquivos,
e o monitor pode levar algum tempo para sincronizar novamente. Não é uma
playlist sem intervalos. Arquivos ausentes, inválidos ou HDR interrompem
a sequência, sem serem pulados silenciosamente.

O seletor de repetição oferece **Não repetir**, **Repetir arquivo** e
**Repetir playlist**. Repetir arquivo mantém somente o item atual em loop;
repetir playlist volta ao primeiro após o último. **Parar** também cancela
um avanço automático que esteja sendo preparado.

**Salvar lista** grava M3U8 em UTF-8 com caminhos absolutos. **Abrir lista**
substitui a lista atual; aceita M3U/M3U8 em UTF-8, comentários ``#EXTINF`` e
caminhos relativos ao diretório da playlist e links individuais do YouTube.
A lista pode misturar arquivos locais e vídeos online. Também se pode abrir
a playlist pelo terminal::

    ./bmdmpv-gui /caminho/sessao.m3u8

Use **Salvar perfil** para guardar placa, resolução/modo HDMI, enquadramento,
saída de áudio, volume, mute, atraso, repetição, opção de decodificação e
navegador para os cookies do YouTube e preferência por 50/60 Hz na HDMI.
Escolha um nome existente para atualizá-lo. Para recuperar as opções,
selecione o perfil e clique em **Aplicar**, com a reprodução parada.
**Excluir** remove o perfil escolhido. A playlist é salva separadamente;
o perfil não contém os arquivos e não inicia reprodução.

Os perfis ficam em ``$XDG_CONFIG_HOME/bmdmpv/profiles.json`` ou, normalmente,
``~/.config/bmdmpv/profiles.json``. A gravação é atômica; arquivos inválidos
são preservados e o erro é mostrado ao tentar salvar/aplicar. Nenhum perfil
é aplicado automaticamente ao abrir a GUI. Uma interface de áudio ausente
impede aplicar o perfil inteiro, sem redirecionamento silencioso. A placa é
identificada pelo índice e nome; se o índice mudou, um nome único pode ser
usado para localizá-la novamente.

Vídeos do YouTube
-----------------

Com a reprodução parada, clique em **YouTube…**, cole o link e confirme.
O vídeo é acrescentado à playlist e a GUI consulta título, resolução, FPS
e duração usando o ``yt-dlp`` instalado no PATH. Clique em **Reproduzir**
para iniciar. A escolha de saída de áudio e o modo HDMI automático funcionam
como para arquivos locais. Também é possível abrir um link pelo terminal::

    ./bmdmpv-gui 'https://www.youtube.com/watch?v=Jad2vcodBLw'

A seleção busca vídeo SDR até 2160p. O modo HDMI é calculado a partir do
formato selecionado, antes de aplicar a resolução forçada/enquadramento.
O mpv usa seu ``ytdl_hook`` para abrir vídeo e áudio, sem precisar baixar o
arquivo inteiro primeiro. A playlist salva o link original do vídeo; os
endereços temporários dos streams são consultados novamente a cada reprodução.
**Parar** cancela uma consulta em andamento, cujo limite é de 60 segundos.

São aceitos links de vídeos individuais, incluindo links curtos e Shorts.
Parâmetros de início e de playlist no link são descartados; não há importação
de canais/listas inteiras do YouTube nem suporte a transmissões ao vivo nesta
versão. A integração ignora a configuração pessoal do yt-dlp.

Em **Cookies do YouTube**, escolha o navegador em que está conectado à sua
conta (inclusive YouTube Premium): Firefox, Chrome, Chromium, Edge, Brave,
Opera ou Vivaldi. O yt-dlp lê os cookies diretamente do navegador, tanto na
consulta quanto na reprodução, usando seu perfil padrão. Trocar o navegador
refaz a consulta do item selecionado. **Sem cookies** mantém o acesso anônimo.
A opção fica salva com **Salvar perfil**; perfis antigos continuam válidos e
usam acesso sem cookies até você escolher um navegador.

Somente o nome do navegador é salvo no perfil, sem exportar um arquivo de
cookies. Para sessões autenticadas, o diagnóstico usa mensagens normais do
mpv em vez do log de depuração, que pode incluir valores de cookies.
Desde o pacote **0.1.1-1**, a GUI procura runtimes no PATH e também em
``~/.local/bin``, ``~/.deno/bin`` e ``~/.bun/bin``, inclusive quando aberta
pelo menu. Verifica a versão antes de escolher: Deno >= 2.3, Node >= 22,
QuickJS compatível ou Bun 1.2.11–1.3.14 (nessa ordem). Uma versão antiga no
PATH não impede localizar uma instalação compatível do usuário. Se nenhuma
for encontrada, mostra uma mensagem específica antes de consultar o vídeo.
O mesmo caminho absoluto é usado na análise e na reprodução pelo mpv.
Não altera o PATH do sistema nem instala outro runtime automaticamente.
Essa correção resolve o erro “Requested format is not available” observado
ao abrir pelo menu sem o Deno de ``~/.local/bin`` no PATH.

O yt-dlp pode baixar o componente EJS oficial do GitHub,
como no downmedia. Consulte a `documentação do EJS
<https://github.com/yt-dlp/yt-dlp/wiki/EJS>`_.

O build requer Lua 5.2 para habilitar o ``ytdl_hook``. Em um build anterior,
com os headers já disponíveis, execute ``./build-mpv.sh -Dlua=lua5.2``.
O bootstrap prepara essa dependência localmente.

**Estado da validação (03/10/2026):** o link acima foi identificado como
“Sam Fender - Hypersonic Missiles (Live At London Stadium)”, em 1080p25,
com sugestão inicial do modo ``Hp25``. O acesso anônimo retornava HTTP 403, inclusive
diretamente pelo yt-dlp. Com cookies do **Firefox** e a configuração JavaScript
acima, vídeo e áudio abriram na DeckLink, mas a tela ficou sem sinal em 25 Hz.
O usuário confirmou imagem em **1080p50**, usando CPU. A seleção automática
agora sugere ``Hp50`` com a preferência por 50/60 Hz ativa. O teste passou com
formatos ``721+251``, buffer de imagem não preto, pausa, busca, retomada e
encerramento. O áudio ficou silenciado no teste. O yt-dlp do sistema não foi
substituído. Logs: ``test-results/youtube-video-auto-check.log`` e
``test-results/youtube-hardware.log``. ``test-results/youtube-frame-cpu.png``
registra o buffer enviado ao SDK, sem representar uma captura física da HDMI.

Decodificação acelerada
----------------------

A Intensity funciona como saída de quadros já decodificados: o caminho
``IDeckLinkOutput`` do SDK usa buffers de imagem, não fornece um decodificador
de arquivos H.264/HEVC para este uso. A decodificação pode ficar na CPU ou
na GPU do computador, antes de enviar a imagem à placa.

O seletor **Decodificação** oferece:

* **CPU**: mantém o comportamento anterior (``--hwdec=no``).
* **GPU · automática**: ``--hwdec=auto-copy``; tenta métodos compatíveis e
  usa CPU quando o codec, driver ou dispositivo não permitem aceleração.
* **NVIDIA · NVDEC**: ``--hwdec=nvdec-copy``.
* **Intel / AMD · VA-API**: ``--hwdec=vaapi-copy``; requer hardware e driver
  VA-API compatíveis. Esta opção não foi validada fisicamente nesta máquina NVIDIA.

A GUI mostra o decodificador **realmente usado**, consultando a propriedade
``hwdec-current`` do mpv. Escolher GPU não significa que todos os arquivos
serão acelerados. Os perfis guardam a opção solicitada, e o resultado é
consultado novamente a cada arquivo. Nesta máquina, com RTX A4500 e driver
615.71.09, H.264 e HEVC SDR 8 bits foram decodificados por ``nvdec-copy`` com
``--vo=decklink`` e áudio HDMI. Um clipe MPEG-4 fora da lista padrão de codecs
acelerados do mpv foi reproduzido pela CPU e identificado como tal na GUI.

Os modos com sufixo ``-copy`` devolvem os quadros da GPU à RAM, permitindo
o processamento por CPU e o uso deste VO. Essa cópia tem custo; o upscale,
downscale, conversão para UYVY e OSD continuam na CPU. Não há transferência
direta GPU → Intensity nesta implementação nem garantia de ganho de desempenho
para qualquer arquivo. Veja a `documentação de hardware decoding do mpv
<https://mpv.io/manual/master/#options-hwdec>`_. A aceleração não remove as
restrições SDR/8 bits da saída.

Também funciona no launcher de terminal, sem recompilar::

    ./mpv-decklink --hwdec=auto-copy --vo-decklink-mode=Hp29 video-h264.mp4
    ./mpv-decklink --hwdec=nvdec-copy --vo-decklink-mode=Hp29 video-hevc.mp4

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
headers do FFmpeg, libass, Lua 5.2 (para YouTube) e libplacebo >= 7.360.1.
Este Debian 13 oferece
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
      -Ddecklink-sdk='/caminho/SDK/Linux/include' -Dmanpage-build=disabled -Dlua=lua5.2
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
    python3 tests/test_gui.py
    python3 tests/test_library.py
    python3 tests/test_youtube.py
    python3 tests/test_js_runtime.py
    python3 tests/test-youtube-ipc.py
    python3 tests/test-youtube-ipc.py --with-cookies

Os dez testes da GUI verificam seleção de modos, taxas fracionárias,
resolução forçada, metadados, seleção de áudio, argumentos sem shell e
seleção de decodificação com cópia para RAM, além de controle IPC com o mpv
real usando saídas nulas. O teste IPC precisa de
permissão para sockets Unix locais, mas não acessa a placa nem emite som.
Os seis testes de persistência cobrem ordem da playlist, M3U8, perfis,
compatibilidade com perfis antigos, validação de dados e preservação do
arquivo anterior em falhas de gravação.
Os sete testes de YouTube cobrem links, formatos SDR, metadados, argumentos,
seleção do navegador nas duas etapas,
playlist mista e cancelamento com encerramento do extrator. O teste adicional
``test-youtube-ipc.py`` usa um extrator simulado e streams HTTP locais separados
para exercitar o ``ytdl_hook`` real, áudio/vídeo, pausa, busca e encerramento.
Requer FFmpeg, Lua habilitada no mpv e sockets locais; não acessa o YouTube.
Os cinco testes de runtime cobrem o PATH reduzido do menu, instalações do
usuário, versões antigas, fallback, ausência e falhas de execução.
A variante ``--with-cookies`` usa cookies simulados e verifica que seus
valores não aparecem no diagnóstico; não lê cookies reais do navegador.

Com uma sessão gráfica, sem acessar a placa::

    python3 tests/test_gui_state.py

Esses nove testes usam player e dispositivos simulados para verificar
avanço, repetição, troca de formato, cancelamento durante análise/transição,
resultados atrasados de consultas, arquivos inválidos e aplicação atômica
de perfis com interface de áudio ausente, além da inclusão e cancelamento
de consultas do YouTube, a preferência por 50/60 Hz e seleção de trilhas por
ID (inclusive descarte de eventos antigos). São 32 testes unitários nos quatro arquivos
``test_gui.py``, ``test_library.py``, ``test_youtube.py`` e ``test_gui_state.py``.

Teste de trilhas com GUI e mpv reais, usando duas trilhas de áudio e duas
legendas em um arquivo sintético::

    python3 tests/test-tracks.py

Usa saídas nulas por padrão. ``--hardware`` envia imagem pela Intensity em
1080p50 com áudio silenciado e compara os buffers com cada legenda e sem
legenda. Verifica troca durante pausa/reprodução e preservação do processo.
``--app-root /usr/lib/bmdmpv`` permite testar a instalação do pacote.

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
    python3 tests/test-gui-hardware.py
    python3 tests/test-playlist-hardware.py

O teste físico da GUI também requer uma sessão gráfica com Tkinter e Pillow.
Ele abre a janela e reproduz um padrão com tom baixo: verifica áudio HDMI
e PipeWire, saída 1080p/720p, os três enquadramentos, pausa, busca, mute,
atraso do áudio, fim de arquivo/reinício e encerramento durante reprodução.
Logs e screenshots são gravados em ``test-results/``. Os screenshots de
vídeo verificam o buffer enviado; não são uma captura física da HDMI.

O teste de playlist requer GPU NVIDIA/NVDEC e gera clipes H.264/HEVC SDR:
verifica decodificação real por GPU com áudio HDMI silenciado e preferência
por 50/60 Hz desativada, transição
automática 1080p29,97 → 720p50 → 1080p29,97, repetição da lista, perfis e
reprodução pela CPU de um clipe não elegível para aceleração automática.
Os logs ficam em ``test-results/playlist-gpu-*.log``.

O teste online é separado e requer acesso aos streams do YouTube::

    python3 tests/test-youtube-hardware.py --browser firefox --url 'https://www.youtube.com/watch?v=Jad2vcodBLw'

Ele verifica a inclusão pela GUI, metadados, buffer de vídeo não preto,
envio ao SDK com áudio silenciado, pausa, busca e encerramento. A imagem
no monitor exige confirmação visual. Use ``--cpu`` para decodificação por
software, ``--mode Hp50`` para forçar esse modo e ``--hold 45`` para observar
a saída durante 45 segundos. Sem ``--browser``, testa o acesso anônimo.

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

``gui/app.py`` controla a interface Tk e a sequência da playlist; cada item
é analisado antes de criar um processo mpv com seu próprio modo de saída.
``gui/core.py`` faz descoberta, escolha de modo e IPC em threads separadas.
``gui/library.py`` contém playlist/M3U8 e persistência de perfis;
``gui/profiles.py`` e ``gui/playlist_window.py`` implementam seus controles.
``gui/sources.py`` valida fontes locais e links do YouTube;
``gui/youtube.py`` consulta os formatos com o yt-dlp em um processo cancelável.

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
