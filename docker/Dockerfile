# Wine + Microsoft .NET Framework 4.8 for the "Legend of Zelda [reloaded]"
# randomizer. Real .NET rather than wine-mono keeps output identical to Windows.
FROM debian:bookworm-slim
RUN sed -i 's/Components: main/Components: main contrib/' /etc/apt/sources.list.d/debian.sources \
 && dpkg --add-architecture i386 && apt-get update \
 && apt-get install -y --no-install-recommends wine wine32 wine64 winetricks cabextract \
      ca-certificates curl xvfb xauth fonts-liberation fontconfig procps \
 && rm -rf /var/lib/apt/lists/*
RUN useradd -u 1000 -m u
USER u
ENV WINEDEBUG=-all WINEARCH=win32 WINEPREFIX=/home/u/.wine
RUN xvfb-run -a winetricks -q --unattended dotnet48 && wineserver -w
# The spoiler-map renderer asks GDI+ for the generic monospace family (Courier
# New). Install it; if the mirror fails, alias Liberation Mono to that name.
RUN (xvfb-run -a winetricks -q --unattended courier || \
     wine reg add 'HKCU\Software\Wine\Fonts\Replacements' /v 'Courier New' /d 'Liberation Mono' /f) \
 && wineserver -w
