import { Link } from 'react-router';

import { cssVars, cx } from '@/lib/cx';

import styles from './KitchenSink.module.css';

const SIGNALS = [
  { token: 'signal', name: 'Signal', hex: '#7FA8B4', sense: 'mesure, neutre' },
  { token: 'effort', name: 'Effort', hex: '#8AA37B', sense: 'série tenue' },
  { token: 'load', name: 'Charge', hex: '#C39B6E', sense: 'seuil approché' },
  { token: 'recover', name: 'Récup', hex: '#A9748A', sense: 'dette, alerte' },
] as const;

const SURFACES = [
  { token: 'bg', name: 'Fond', hex: '#0B0F16' },
  { token: 'surface', name: 'Surface', hex: '#131A24' },
  { token: 'surface-2', name: 'Surface haute', hex: '#18212D' },
] as const;

const SPACES = ['s1', 's2', 's3', 's4', 's5', 's6', 's7', 's8'] as const;

/**
 * Référence visuelle du projet (`L00-08`).
 *
 * À ce lot elle couvre les *tokens* : couleurs, typographie, niveaux d'intensité,
 * espacement. Elle devient la galerie complète des composants au lot L03 (`L03-11`),
 * une fois `components/ui/` écrit.
 */
export function KitchenSink() {
  return (
    <main className="wrap">
      <p className="eyebrow">Référence visuelle · tokens · v0.1.0</p>
      <h1 style={{ marginTop: 10 }}>Charte</h1>
      <p className="lede" style={{ marginTop: 14 }}>
        Reprise fidèle de <code>GuidelinesUI.html</code>. Cette page est le test visuel du projet :
        toute dérive de la charte se voit ici avant de se voir dans un écran.
      </p>

      {/* ══ COULEURS ══ */}
      <div className="rule">
        <span>01 — Couleurs</span>
      </div>
      <p className="lede" style={{ marginBottom: 20 }}>
        Une base sombre mate, quatre signaux désaturés. Chaque couleur porte un sens fixe dans l'app
        : on ne l'utilise jamais pour décorer.
      </p>
      <div className="grid g4">
        {SIGNALS.map((c) => (
          <div className={styles.swatch} key={c.token}>
            <div className={styles.chip} style={{ background: `var(--${c.token})` }} />
            <div className={styles.meta}>
              <div className={styles.name}>{c.name}</div>
              <div className={styles.hex}>
                {c.hex} · {c.sense}
              </div>
            </div>
          </div>
        ))}
      </div>
      <div className="grid g3 mt">
        {SURFACES.map((c) => (
          <div className={styles.swatch} key={c.token}>
            <div
              className={styles.chip}
              style={{
                background: `var(--${c.token})`,
                borderBottom: c.token === 'bg' ? '1px solid var(--line)' : undefined,
              }}
            />
            <div className={styles.meta}>
              <div className={styles.name}>{c.name}</div>
              <div className={styles.hex}>{c.hex}</div>
            </div>
          </div>
        ))}
      </div>

      {/* ══ TYPOGRAPHIE ══ */}
      <div className="rule">
        <span>02 — Typographie</span>
      </div>
      <div className="grid g2">
        <div className={styles.card}>
          <p className="eyebrow">Display · Space Grotesk</p>
          <p className={cx(styles.specimen, styles.specimenDisplay)}>42,7 km</p>
          <p className={styles.note}>
            Titres, libellés, interface. Ses formes légèrement techniques tiennent bien aux grandes
            tailles et restent lisibles en 13&nbsp;px.
          </p>
          <div className={styles.weights}>
            <span style={{ fontWeight: 400 }}>400 Regular</span>
            <span style={{ fontWeight: 500 }}>500 Medium</span>
            <span style={{ fontWeight: 600 }}>600 SemiBold</span>
            <span style={{ fontWeight: 700 }}>700 Bold</span>
          </div>
        </div>
        <div className={styles.card}>
          <p className="eyebrow">Data · JetBrains Mono</p>
          <p className={cx(styles.specimen, styles.specimenMono)}>04:31:08</p>
          <p className={styles.note}>
            Tout ce qui est chiffre, unité, horodatage, en-tête de colonne. Chasse fixe : les
            colonnes s'alignent seules, l'œil compare sans effort.
          </p>
          <div className={styles.weights} style={{ fontFamily: 'var(--mono)' }}>
            <span style={{ fontWeight: 400 }}>400</span>
            <span style={{ fontWeight: 500 }}>500</span>
            <span style={{ fontWeight: 700 }}>700</span>
            <span className="num" style={{ fontWeight: 400 }}>
              0123456789 œ é à ç ù
            </span>
          </div>
        </div>
      </div>

      {/* ══ NIVEAUX D'INTENSITÉ ══ */}
      <div className="rule">
        <span>03 — Niveaux d'intensité</span>
      </div>
      <p className="lede" style={{ marginBottom: 20 }}>
        Les quatre niveaux d'une cellule de heatmap sont dérivés d'une seule couleur d'accent par
        opacité. C'est ce qui permet à chaque piste de porter la sienne (<code>HEAT-20</code>) sans
        dupliquer quatre variantes par couleur.
      </p>
      <div className={styles.card}>
        {SIGNALS.map((c) => (
          <div
            className={styles.levelRow}
            key={c.token}
            style={cssVars({ '--accent-rgb': `var(--${c.token}-rgb)` })}
          >
            <span className={styles.levelLabel}>{c.name}</span>
            <i className={cx(styles.cell, styles.cell0)} />
            <i className={cx(styles.cell, styles.cell1)} />
            <i className={cx(styles.cell, styles.cell2)} />
            <i className={cx(styles.cell, styles.cell3)} />
            <i className={cx(styles.cell, styles.cell4)} />
            <span className={styles.levelHint}>off · 1 · 2 · 3 · 4</span>
          </div>
        ))}
      </div>

      {/* ══ ESPACEMENT ══ */}
      <div className="rule">
        <span>04 — Espacement</span>
      </div>
      <div className={styles.card}>
        {SPACES.map((s) => (
          <div className={styles.spaceRow} key={s}>
            <span>--{s}</span>
            <div className={styles.spaceBar} style={{ width: `var(--${s})` }} />
          </div>
        ))}
      </div>

      <div className="rule">
        <span>Fin</span>
      </div>
      <p className="eyebrow" style={{ paddingBottom: 20 }}>
        <Link to="/">← Retour</Link>
      </p>
    </main>
  );
}
