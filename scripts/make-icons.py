#!/usr/bin/env python3
"""Dessine les icônes de l'application depuis le motif signature de la charte (`L15-01`).

`GuidelinesUI.html` nomme la règle graduée « motif signature » : un trait de 1 px en
`--line`, surmonté de graduations tous les 16 px. C'est ce qui sépare chaque section de
chaque écran depuis le lot L00, et c'est la seule forme que le dépôt possède en propre —
`components/ui/icons.tsx` ne porte que des pictogrammes d'interface.

**Le motif est repris à l'échelle du pavé, pas à ses valeurs CSS.** Un trait de 1 px et des
graduations de 5 px disparaissent à 48 px sur un écran d'accueil : l'icône serait un carré
vide, ce qui est pire que pas d'icône. Les épaisseurs sont donc proportionnelles au côté du
pavé. C'est le même motif ; ce ne sont pas les mêmes pixels.

Un script plutôt que quatre fichiers binaires posés à la main : les couleurs viennent de
`tokens.css` et devront le suivre, et une icône qu'on ne sait pas redessiner est une icône
qu'on ne corrige jamais.

Usage — depuis la racine du dépôt, avec le Python du backend (il porte Pillow) :

    backend/.venv/bin/python scripts/make-icons.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

# ── Couleurs, reprises de `frontend/src/styles/tokens.css` ────────────────────
#
# Le thème sombre est celui de la charte et la valeur par défaut de `:root`. Un manifeste
# ne porte qu'une couleur là où l'application en a deux : c'est celle-ci, et
# `tokens.test.ts` vérifie qu'elles ne dérivent pas.
BG = (0x0B, 0x0F, 0x16)  # --bg
SIGNAL = (0x7F, 0xA8, 0xB4)  # --signal — la mesure, le neutre

#: Opacité des graduations. Dans la charte elles sont en `--line`, qui sur `--bg` tient un
#: contraste de 1,3:1 — juste ce qu'il faut pour un séparateur de 1 px vu à 40 cm, et très
#: loin de ce qu'il faut pour une icône vue à 48 px. Elles passent donc en `--signal`
#: atténué : même teinte que le trait, hiérarchie conservée, et elles restent visibles.
TICK_ALPHA = 0.45

#: Nombre de graduations. La charte les répète tous les 16 px sur toute la largeur ; six
#: est ce qui garde un rythme lisible une fois le motif ramené à un carré.
TICKS = 6

OUT = Path(__file__).resolve().parent.parent / "frontend" / "public" / "icons"


def draw(size: int, *, extent: float) -> Image.Image:
    """Rend le motif sur un pavé de `size` px.

    `extent` est la fraction du côté qu'occupe la largeur du trait. C'est le seul réglage
    entre les variantes : une icône Android adaptative est rognée jusqu'au cercle inscrit
    à 80 %, et le motif doit y entrer entièrement.
    """
    image = Image.new("RGB", (size, size), BG)
    canvas = ImageDraw.Draw(image, "RGBA")

    width = size * extent
    left = (size - width) / 2
    right = left + width

    # Le trait, et son épaisseur : 1/24 du côté. En deçà, il se confond avec le fond une
    # fois l'icône réduite par le lanceur ; au-delà, il cesse d'être une règle graduée
    # pour devenir une barre.
    stroke = max(2.0, size / 24)

    # Les graduations montent **depuis** le trait, comme dans `.rule::before`. Elles sont
    # plus fines que lui — moitié moins — et hautes de deux fois son épaisseur.
    tick_w = max(1.0, stroke / 2)
    tick_h = stroke * 2

    # Le motif dessiné est plus haut que son trait : c'est le **bloc entier** qui se
    # centre, graduations comprises. Centrer le trait seul décale la composition vers le
    # haut de la moitié de la hauteur des graduations — 34 px sur un pavé de 512, et ça se
    # voit d'un coup d'œil sur l'icône finale.
    baseline = (size + tick_h + stroke) / 2

    canvas.rectangle(
        (left, baseline - stroke, right, baseline),
        fill=SIGNAL,
    )
    step = width / (TICKS - 1)
    tint = (*SIGNAL, round(255 * TICK_ALPHA))

    for index in range(TICKS):
        x = left + index * step
        # Les graduations extrêmes sont ramenées vers l'intérieur pour rester entièrement
        # dans le pavé : à `extent = 1`, la moitié de chacune tomberait hors du bord.
        x = min(max(x, left + tick_w / 2), right - tick_w / 2)
        canvas.rectangle(
            (x - tick_w / 2, baseline - stroke - tick_h, x + tick_w / 2, baseline - stroke),
            fill=tint,
        )

    return image


#: Les quatre variantes.
#:
#: `extent` descend à 0,50 pour la maskable : Android rogne jusqu'au cercle inscrit à 80 %
#: du côté, et un motif horizontal y perd ses extrémités bien avant un motif centré. 0,50
#: laisse le trait entier dans le cercle sûr, graduations comprises.
#:
#: iOS ignore le manifeste et applique son propre masque à coins arrondis, sans rogner
#: aussi loin : 0,62 lui laisse de la marge sans rapetisser le motif pour rien.
VARIANTS: tuple[tuple[str, int, float], ...] = (
    ("icon-192.png", 192, 0.70),
    ("icon-512.png", 512, 0.70),
    ("icon-maskable-512.png", 512, 0.50),
    ("apple-touch-icon.png", 180, 0.62),
)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, size, extent in VARIANTS:
        image = draw(size, extent=extent)
        # `optimize` seulement : une icône est un asset versionné, pas un flux. La
        # reproductibilité du fichier compte plus que les quelques octets d'un recodage.
        image.save(OUT / name, "PNG", optimize=True)
        print(f"  {name:<28} {size}×{size}  trait sur {extent:.0%} du côté")
    print(f"\n{len(VARIANTS)} icônes écrites dans {OUT.relative_to(Path.cwd())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
