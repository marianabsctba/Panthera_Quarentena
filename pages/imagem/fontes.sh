#!/usr/bin/env bash
# Publica na release "fontes" uma copia do codigo-fonte de cada programa GPL, LGPL
# ou MPL que a imagem leva: a receita do Alpine (com os patches) e os arquivos
# originais, conferidos pelo checksum da receita. Roda depois do construir.sh e so
# envia o que ainda nao esta la. Precisa de root para o chroot.
# SEM_ENVIO=1 testa sem enviar; SO="bash upx" limita a alguns projetos.
set -euo pipefail

AQUI="$(cd "$(dirname "$0")" && pwd)"
RAIZ="$(cd "$AQUI/../.." && pwd)"
TSV="$RAIZ/pages/saida/pacotes.tsv"
TRAB="${TRAB:-/tmp/quarentena-imagem}"
AUX="$TRAB/aux"
ALPINE_RAMO="v3.21"
RELEASE="fontes"
REPO="${GITHUB_REPOSITORY:-marianabsctba/Panthera_Quarentena}"
# As mesmas de pages/gerar_site.py, que aponta o link para estes arquivos.
V86_COMMIT="cc37f35c43bf14865d74ad76879ecf9410f69eb1"
SEABIOS="1.16.2"

trap 'umount -l "$AUX/dev" 2>/dev/null || true' EXIT
mount --rbind /dev "$AUX/dev"
# O APKBUILD e codigo de terceiros: dentro do chroot nao entra o token.
dentro() { env -u GH_TOKEN chroot "$AUX" /bin/sh -c "$1"; }
dentro 'apk add --no-cache --quiet abuild'
PASTA="$AUX/fontes"
rm -rf "$PASTA"
mkdir -p "$PASTA/aports"
git -C "$PASTA/aports" init -q
git -C "$PASTA/aports" remote add origin https://github.com/alpinelinux/aports.git

existentes=""
if [ -z "${SEM_ENVIO:-}" ]; then
  gh release view "$RELEASE" --repo "$REPO" >/dev/null 2>&1 || gh release create "$RELEASE" --repo "$REPO" \
    --title "Código-fonte dos programas do Linux" \
    --notes "Cópia do código-fonte dos programas GPL, LGPL e MPL que o Panthera Quarentena distribui no navegador. Cada arquivo traz a receita de compilação do Alpine Linux, com os patches, e os arquivos originais. A lista completa está na página de licenças: https://marianabsctba.github.io/Panthera_Quarentena/licencas.html"
  existentes="$(gh release view "$RELEASE" --repo "$REPO" --json assets --jq '.assets[].name')"
fi

quer() { [ -z "${SO:-}" ] || case " $SO " in *" $1 "*) return 0;; *) return 1;; esac; }
ja_tem() { printf '%s\n' "$existentes" | grep -qxF "$1"; }
enviar() {
  ls -l "$1" | awk '{printf "%s  %.1f MB\n", $9, $5/1048576}'
  [ -n "${SEM_ENVIO:-}" ] || gh release upload "$RELEASE" "$1" --repo "$REPO"
  rm -f "$1"
}

falhas=""
montar() {
  local ori="$1" ver="$2" com="$3" rep="$4" nome="$ori-$ver.tar.gz"
  local dir="$PASTA/$nome.d"
  mkdir -p "$dir"
  git -C "$PASTA/aports" fetch -q --depth 1 --filter=blob:none origin "$com"
  git -C "$PASTA/aports" checkout -q FETCH_HEAD -- "$rep/$ori"
  cp -r "$PASTA/aports/$rep/$ori" "$dir/receita"
  mkdir "$dir/originais"
  dentro "cd '/fontes/$nome.d/receita' && SRCDEST='/fontes/$nome.d/originais' \
    DISTFILES_MIRROR=https://distfiles.alpinelinux.org/distfiles/$ALPINE_RAMO abuild -F fetch verify" >/dev/null
  tar czf "$PASTA/$nome" -C "$dir" --transform "s,^,$ori-$ver/," receita originais
  enviar "$PASTA/$nome"
}

while IFS=$'\t' read -r ori ver com rep; do
  quer "$ori" || continue
  ja_tem "$ori-$ver.tar.gz" && continue
  echo "== $ori $ver"
  montar "$ori" "$ver" "$com" "$rep" || falhas="$falhas $ori"
  rm -rf "$PASTA/$ori-$ver.tar.gz.d"
done < <(awk -F'\t' '$4 ~ /GPL|MPL/ { print $3 "\t" $2 "\t" $5 "\t" $6 }' "$TSV" | sort -u)

# As duas BIOS vem do SeaBIOS, compilado pelo v86 com estas configuracoes.
nome="seabios-$SEABIOS.tar.gz"
if quer seabios && ! ja_tem "$nome"; then
  echo "== seabios $SEABIOS"
  dir="$PASTA/seabios"
  mkdir -p "$dir/seabios-$SEABIOS/v86"
  curl -fsSL "https://codeload.github.com/coreboot/seabios/tar.gz/refs/tags/rel-$SEABIOS" \
    -o "$dir/seabios-$SEABIOS/seabios-rel-$SEABIOS.tar.gz"
  for f in fetch-and-build-seabios.sh seabios.config COPYING.LESSER; do
    curl -fsSL "https://raw.githubusercontent.com/copy/v86/$V86_COMMIT/bios/$f" -o "$dir/seabios-$SEABIOS/v86/$f"
  done
  tar czf "$PASTA/$nome" -C "$dir" "seabios-$SEABIOS"
  enviar "$PASTA/$nome"
fi

if [ -n "$falhas" ]; then
  echo "falhou:$falhas" >&2
  exit 1
fi
echo "ok: fontes"
