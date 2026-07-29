import { useState } from 'react';

import {
  AiBlock,
  Badge,
  Bars,
  Button,
  Card,
  Chart,
  Check,
  CheckGroup,
  Empty,
  Field,
  Heatmap,
  LogButton,
  Progress,
  Ring,
  Rule,
  Segmented,
  Sparkline,
  Stat,
  Table,
} from '@/components/ui';
import type { Column, HeatDay, HeatWeek, Tone } from '@/components/ui';
import { cssVars, cx } from '@/lib/cx';
import { duration, km, pace } from '@/lib/format';
import { useToast } from '@/lib/toast';

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

const PERIODS = [
  { value: '7j', label: '7J' },
  { value: '30j', label: '30J' },
  { value: '90j', label: '90J' },
  { value: 'an', label: 'AN' },
] as const;

type Period = (typeof PERIODS)[number]['value'];

// ── Données de démonstration ──────────────────────────
// Reprises de la charte. Elles ne servent qu'à cette page : aucun écran applicatif
// n'affiche de valeur inventée — dans une application de mesure ce serait la pire des
// démonstrations.

const PACE = [
  6.05, 5.98, 6.1, 5.92, 5.88, 5.95, 5.8, 5.86, 5.74, 5.79, 5.68, 5.72, 5.61, 5.66, 5.55, 5.6, 5.48,
  5.52, 5.44, 5.5, 5.38, 5.42, 5.31, 5.36, 5.26, 5.3, 5.21, 5.24, 5.16, 5.12,
];
const LOAD = [
  38, 42, 40, 47, 52, 49, 55, 58, 54, 60, 63, 59, 66, 70, 65, 72, 75, 70, 78, 74, 80, 84, 79, 86,
  90, 85, 92, 88, 94, 97,
];
const SLEEP = [
  7.6, 7.4, 7.8, 7.2, 7.5, 7.0, 7.3, 6.9, 7.1, 6.8, 7.2, 6.6, 6.9, 6.4, 6.7, 6.3, 6.6, 6.1, 6.5,
  6.0, 6.3, 5.8, 6.2, 5.6, 6.0, 5.5, 6.1, 5.4, 5.9, 5.3,
];

const LABELS = PACE.map((_, index) =>
  index === PACE.length - 1 ? 'AUJ' : `J-${PACE.length - 1 - index}`,
);

/** Grille de démonstration : une piste « deux fois par semaine », donc surtout `off`. */
function demoDays(): HeatDay[] {
  const days: HeatDay[] = [];
  const start = new Date();
  start.setDate(start.getDate() - 370);
  let seed = 7;
  const random = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;

  for (let index = 0; index < 371; index += 1) {
    const date = new Date(start);
    date.setDate(start.getDate() + index);
    const iso = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
    const draw = random();

    if (index < 40) {
      days.push({ date: iso, value: 0, state: 'off', level: 0, reason: 'before_track' });
    } else if (index > 200 && index < 209) {
      days.push({ date: iso, value: 0, state: 'off', level: 0, reason: 'neutralised' });
    } else if (draw < 0.28) {
      days.push({
        date: iso,
        value: Math.ceil(draw * 12),
        state: 'done',
        level: Math.min(4, 1 + Math.floor(draw * 14)),
      });
    } else if (draw < 0.34) {
      days.push({ date: iso, value: 0, state: 'missed', level: 0 });
    } else if (draw > 0.97) {
      days.push({ date: iso, value: 3, state: 'bonus', level: 2 });
    } else {
      days.push({ date: iso, value: 0, state: 'off', level: 0 });
    }
  }
  return days;
}

function demoWeeks(days: readonly HeatDay[]): HeatWeek[] {
  const weeks: HeatWeek[] = [];
  for (let index = 0; index < days.length; index += 7) {
    const slice = days.slice(index, index + 7);
    const first = slice[0];
    if (!first) continue;
    const done = slice.filter((day) => day.state === 'done' || day.state === 'bonus').length;
    weeks.push({
      start: first.date,
      status: done >= 2 ? 'reached' : done === 1 ? 'partial' : 'missed',
      done,
      expected: 2,
    });
  }
  return weeks;
}

const DAYS = demoDays();
const WEEKS = demoWeeks(DAYS);

interface Session {
  date: string;
  kind: string;
  distance: number;
  minutes: number;
  label: string;
  tone: Tone;
}

const SESSIONS: Session[] = [
  {
    date: '25/07',
    kind: 'Endurance',
    distance: 8.4,
    minutes: 44.2,
    label: 'nominal',
    tone: 'effort',
  },
  {
    date: '23/07',
    kind: 'Fractionné',
    distance: 6.1,
    minutes: 32.67,
    label: 'charge',
    tone: 'load',
  },
  {
    date: '21/07',
    kind: 'Récupération',
    distance: 4.0,
    minutes: 25.97,
    label: 'relevé',
    tone: 'signal',
  },
  {
    date: '19/07',
    kind: 'Sortie longue',
    distance: 14.2,
    minutes: 78.73,
    label: 'gêne tendon',
    tone: 'recover',
  },
];

const COLUMNS: Column<Session>[] = [
  { key: 'date', header: 'Date', numeric: true, render: (row) => row.date },
  { key: 'kind', header: 'Type', render: (row) => row.kind },
  { key: 'distance', header: 'Dist.', numeric: true, render: (row) => km(row.distance) },
  { key: 'duration', header: 'Durée', numeric: true, render: (row) => duration(row.minutes) },
  {
    key: 'pace',
    header: 'Allure',
    numeric: true,
    render: (row) => pace(row.minutes / row.distance),
  },
  { key: 'state', header: 'État', render: (row) => <Badge tone={row.tone}>{row.label}</Badge> },
];

interface RoutineItem {
  label: string;
  dose?: string;
  streak?: string;
  done: boolean;
}

const ROUTINE: { group: string; items: RoutineItem[] }[] = [
  {
    group: 'Matin',
    items: [
      { label: 'Créatine', dose: '5 g', streak: '41 j', done: true },
      { label: 'Poids à jeun', dose: '68,4 kg', streak: '12 j', done: true },
      { label: 'Eau', dose: '500 ml', done: false },
    ],
  },
  {
    group: 'Séance · 21:00',
    items: [
      { label: 'Sortie course', dose: '8 km prévu', done: false },
      { label: 'Whey', dose: '30 g · après', done: false },
      { label: 'Mobilité', dose: '10 min', done: false },
    ],
  },
  {
    group: 'Soir',
    items: [
      { label: 'Magnésium', dose: '300 mg', streak: '28 j', done: true },
      { label: 'Lecture', dose: '20 min', done: false },
      { label: 'Au lit avant 23:30', done: false },
    ],
  },
];

/**
 * Référence visuelle du projet (`L03-11`).
 *
 * Chaque composant de la bibliothèque y est rendu. C'est le test visuel : une régression
 * de style saute aux yeux sur une seule page, avant d'atteindre un écran applicatif.
 */
export function KitchenSink() {
  const [period, setPeriod] = useState<Period>('30j');
  const [checked, setChecked] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(
      ROUTINE.flatMap((group) => group.items.map((item) => [item.label, item.done])),
    ),
  );
  const { notify } = useToast();

  const done = Object.values(checked).filter(Boolean).length;
  const total = Object.keys(checked).length;

  return (
    <div className="wrap">
      <p className="eyebrow">Référence visuelle · bibliothèque de composants</p>
      <h1 style={{ marginTop: 10 }}>Charte</h1>
      <p className="lede" style={{ marginTop: 14 }}>
        Reprise fidèle de <code>GuidelinesUI.html</code>. Cette page est le test visuel du projet :
        toute dérive de la charte se voit ici avant de se voir dans un écran.
      </p>

      {/* ══ 01 COULEURS ══ */}
      <Rule>01 — Couleurs</Rule>
      <div className="grid g4">
        {SIGNALS.map((color) => (
          <div className={styles.swatch} key={color.token}>
            <div className={styles.chip} style={{ background: `var(--${color.token})` }} />
            <div className={styles.meta}>
              <div className={styles.name}>{color.name}</div>
              <div className={styles.hex}>
                {color.hex} · {color.sense}
              </div>
            </div>
          </div>
        ))}
      </div>
      <div className="grid g3 mt">
        {SURFACES.map((color) => (
          <div className={styles.swatch} key={color.token}>
            <div
              className={styles.chip}
              style={{
                background: `var(--${color.token})`,
                borderBottom: color.token === 'bg' ? '1px solid var(--line)' : undefined,
              }}
            />
            <div className={styles.meta}>
              <div className={styles.name}>{color.name}</div>
              <div className={styles.hex}>{color.hex}</div>
            </div>
          </div>
        ))}
      </div>

      {/* ══ 02 TYPOGRAPHIE ══ */}
      <Rule>02 — Typographie</Rule>
      <div className="grid g2">
        <Card>
          <p className="eyebrow">Display · Space Grotesk</p>
          <p className={cx(styles.specimen, styles.specimenDisplay)}>42,7 km</p>
          <p className={styles.note}>
            Titres, libellés, interface. Ses formes légèrement techniques tiennent bien aux grandes
            tailles et restent lisibles en 13&nbsp;px.
          </p>
        </Card>
        <Card>
          <p className="eyebrow">Data · JetBrains Mono</p>
          <p className={cx(styles.specimen, styles.specimenMono)}>04:31:08</p>
          <p className={styles.note}>
            Chasse fixe : les colonnes s'alignent seules, l'œil compare sans effort.
            <span className="num"> 0123456789 œ é à ç ù</span>
          </p>
        </Card>
      </div>

      {/* ══ 03 CONTRÔLES ══ */}
      <Rule>03 — Contrôles</Rule>
      <div className="grid g2">
        <Card>
          <h3>Boutons</h3>
          <div className="row mt">
            <Button
              variant="primary"
              onClick={() => {
                notify('Séance enregistrée.', 'effort');
              }}
            >
              Enregistrer la séance
            </Button>
            <Button variant="ghost">Voir l'historique</Button>
            <Button variant="quiet">Annuler</Button>
            <Button variant="ghost" disabled>
              Sync
            </Button>
          </div>

          <h3 style={{ marginTop: 24 }}>Saisie rapide</h3>
          <p className={styles.note}>
            La cible : un relevé en un geste. Ces boutons remplissent le formulaire avec la dernière
            valeur connue.
          </p>
          <div className="stack mt">
            <LogButton label="Course · 5 km" hint="dernier : 27:14" />
            <LogButton label="Sommeil" hint="dernier : 7 h 20" />
            <LogButton label="Session de code" hint="dernier : 2 h 05" />
          </div>
        </Card>

        <Card>
          <h3>Champs</h3>
          <div className="stack mt">
            <Field label="Distance (km)" defaultValue="8.40" />
            <Field label="Durée" defaultValue="00:44:12" />
            <Field label="Ressenti" placeholder="jambes lourdes, vent de face…" />
            <Field
              label="Poids (kg)"
              defaultValue="900"
              error="Doit être inférieur ou égal à 500"
            />
          </div>

          <h3 style={{ marginTop: 24 }}>États</h3>
          <div className="row mt">
            <Badge tone="signal">relevé</Badge>
            <Badge tone="effort">série · 12 j</Badge>
            <Badge tone="load">charge +18 %</Badge>
            <Badge tone="recover">manquant</Badge>
          </div>

          <h3 style={{ marginTop: 24 }}>Période</h3>
          <div className="row mt">
            <Segmented label="Période" value={period} onChange={setPeriod} options={PERIODS} />
          </div>
        </Card>
      </div>

      {/* ══ 04 CHIFFRES CLÉS ══ */}
      <Rule>04 — Chiffres clés</Rule>
      <div className="grid g4">
        <Card>
          <Stat
            label="Volume · 7 j"
            value="31,2"
            unit="km"
            detail="▲ 12 % vs sem. préc."
            direction="up"
            spark={[8, 12, 9, 18, 16, 24, 27]}
            sparkTone="effort"
          />
        </Card>
        <Card>
          <Stat
            label="Sommeil moy."
            value="6:52"
            detail="▼ 21 min vs objectif"
            direction="down"
            spark={[24, 20, 23, 15, 17, 11, 9]}
            sparkTone="recover"
          />
        </Card>
        <Card>
          <Stat
            label="Charge aiguë"
            value="418"
            unit="ua"
            detail="ratio 1,28 — zone haute"
            spark={[10, 13, 12, 19, 21, 25, 28]}
            sparkTone="load"
          />
        </Card>
        <Card>
          <Stat
            label="Jours relevés"
            value="247"
            unit="/365"
            detail="série en cours : 12"
            spark={[14, 16, 15, 20, 19, 22, 23]}
          />
        </Card>
      </div>

      {/* ══ 05 ASSIDUITÉ ══ */}
      <Rule>05 — Assiduité</Rule>
      <Card>
        <div className="spread">
          <div>
            <h3>371 jours · piste « torse »</h3>
            <p className={styles.note}>
              Deux fois par semaine. La grille est majoritairement grise, et ce n'est{' '}
              <strong>pas</strong> un échec : gris veut dire « rien n'était attendu ce jour-là ».
              Seul le mauve accuse. Les hachures sont les jours neutralisés — une grippe ne casse
              pas une série.
            </p>
          </div>
          <Badge tone="effort">série · 12 sem.</Badge>
        </div>
        <div className="mt">
          <Heatmap
            days={DAYS}
            weeks={WEEKS}
            label="Assiduité torse"
            unit="séries"
            accentRgb="var(--effort-rgb)"
          />
        </div>
      </Card>

      {/* ══ 06 GRAPHIQUES ══ */}
      <Rule>06 — Graphiques</Rule>
      <div className="grid g2">
        <Card>
          <div className="spread">
            <div>
              <h3>Répartition du temps</h3>
              <p className="eyebrow" style={{ marginTop: 4 }}>
                semaine 30
              </p>
            </div>
            <Badge tone="load" mono>
              62 h
            </Badge>
          </div>
          <Bars
            rows={[
              { label: 'Sommeil', ratio: 0.88, value: '48 h', tone: 'signal' },
              { label: 'Études', ratio: 0.64, value: '35 h', tone: 'effort' },
              { label: 'Projets', ratio: 0.46, value: '25 h', tone: 'load' },
              { label: 'Sport', ratio: 0.22, value: '12 h', tone: 'recover' },
            ]}
          />
          <div style={{ marginTop: 26 }}>
            <Ring
              ratio={0.78}
              label="Objectif hebdomadaire"
              detail="4 séances sur 5 · reste samedi"
            />
          </div>
        </Card>

        <Card>
          <h3>Régularité par item</h3>
          <p className={styles.note}>
            30 derniers jours. Ce qui décroche se voit ici avant de se voir ailleurs.
          </p>
          <Bars
            rows={[
              { label: 'Créatine', ratio: 0.97, value: '29/30', tone: 'effort' },
              { label: 'Magnésium', ratio: 0.93, value: '28/30', tone: 'effort' },
              { label: 'Whey', ratio: 0.73, value: '22/30', tone: 'signal' },
              { label: 'Mobilité', ratio: 0.47, value: '14/30', tone: 'load' },
              { label: 'Coucher', ratio: 0.3, value: '9/30', tone: 'recover' },
            ]}
          />
          <div className="mt">
            <Sparkline values={PACE.map((value) => -value)} label="Allure sur 30 jours" />
          </div>
        </Card>
      </div>

      {/* ══ 07 ANALYSE CROISÉE ══ */}
      <Rule>07 — Analyse croisée</Rule>
      <Card>
        <div className={styles.chartHead}>
          <div>
            <h3>Allure, charge et sommeil</h3>
            <p className="eyebrow" style={{ marginTop: 4 }}>
              30 derniers jours
            </p>
          </div>
          <Segmented
            label="Période du graphique"
            value={period}
            onChange={setPeriod}
            options={PERIODS}
          />
        </div>
        <Chart
          labels={LABELS}
          primary={{
            label: 'Allure',
            unit: '/km',
            values: PACE,
            tone: 'signal',
            domain: [5.0, 6.2],
            ticks: [5.0, 5.3, 5.6, 5.9, 6.2],
            format: (value) => pace(value),
          }}
          context={{ label: 'Charge', unit: 'ua', values: LOAD, tone: 'load' }}
          band={{
            label: 'Sommeil',
            unit: 'h',
            values: SLEEP,
            tone: 'effort',
            alertBelow: 6.5,
            domain: [5, 8],
            format: (value) => `${Math.floor(value)} h`,
          }}
          note={
            <>
              Les barres sous l'axe passent en{' '}
              <span style={{ color: 'var(--recover)' }}>mauve</span> sous 6 h 30. Trois barres
              mauves d'affilée et la bande de charge s'épaissit : c'est le signal qu'on cherche à
              voir venir.
            </>
          }
        />
      </Card>

      {/* ══ 08 ROUTINE ══ */}
      <Rule>08 — Routine du jour</Rule>
      <div className="grid g2">
        <Card>
          <div className="spread">
            <div>
              <h3>Samedi 26 juillet</h3>
              <p className="eyebrow" style={{ marginTop: 4 }}>
                jour de séance
              </p>
            </div>
            <Badge tone="effort">
              {done}/{total}
            </Badge>
          </div>

          {ROUTINE.map((group) => (
            <CheckGroup title={group.group} key={group.group}>
              {group.items.map((item) => (
                <Check
                  key={item.label}
                  label={item.label}
                  dose={item.dose}
                  streak={item.streak}
                  checked={checked[item.label] ?? false}
                  onToggle={() => {
                    setChecked((current) => ({
                      ...current,
                      [item.label]: !(current[item.label] ?? false),
                    }));
                  }}
                />
              ))}
            </CheckGroup>
          ))}

          <Progress done={done} total={total} />
        </Card>

        <div className="stack">
          <AiBlock
            tag="Corrélation"
            actions={<Button variant="ghost">Mettre un rappel 20:45</Button>}
          >
            <p>
              Les jours où <strong>Mobilité</strong> est cochée, ton allure du lendemain gagne{' '}
              <strong>7 s/km</strong> en moyenne. C'est l'item le moins suivi de ta routine et celui
              qui pèse le plus.
            </p>
          </AiBlock>

          <Empty
            title="Aucun relevé aujourd'hui"
            action={<Button variant="primary">Relever maintenant</Button>}
          >
            Deux chiffres suffisent pour que la journée compte.
            <br />
            Trente secondes, et la série tient.
          </Empty>
        </div>
      </div>

      {/* ══ 09 TABLEAU ══ */}
      <Rule>09 — Tableau</Rule>
      <Card flush>
        <h3 className={styles.tableTitle}>Dernières séances</h3>
        <Table
          columns={COLUMNS}
          rows={SESSIONS}
          rowKey={(row) => row.date}
          caption="Dernières séances"
        />
      </Card>

      {/* ══ 10 NIVEAUX ET ESPACEMENT ══ */}
      <Rule>10 — Niveaux d'intensité et espacement</Rule>
      <div className="grid g2">
        <Card>
          <p className={styles.note} style={{ marginTop: 0 }}>
            Les quatre niveaux dérivent d'une seule couleur d'accent par opacité : chaque piste
            porte la sienne sans dupliquer quatre variantes.
          </p>
          <div className="mt">
            {SIGNALS.map((color) => (
              <div
                className={styles.levelRow}
                key={color.token}
                style={cssVars({ '--accent-rgb': `var(--${color.token}-rgb)` })}
              >
                <span className={styles.levelLabel}>{color.name}</span>
                <i className={cx(styles.cell, styles.cell0)} />
                <i className={cx(styles.cell, styles.cell1)} />
                <i className={cx(styles.cell, styles.cell2)} />
                <i className={cx(styles.cell, styles.cell3)} />
                <i className={cx(styles.cell, styles.cell4)} />
                <span className={styles.levelHint}>off · 1 · 2 · 3 · 4</span>
              </div>
            ))}
          </div>
        </Card>

        <Card>
          {SPACES.map((space) => (
            <div className={styles.spaceRow} key={space}>
              <span>--{space}</span>
              <div className={styles.spaceBar} style={{ width: `var(--${space})` }} />
            </div>
          ))}
        </Card>
      </div>

      <Rule>Fin</Rule>
      <p className="eyebrow" style={{ paddingBottom: 40 }}>
        Metric — aleksi.systems
      </p>
    </div>
  );
}
