/**
 * Import d'une capture Apple sur l'écran Activité (`IMP-01` → `IMP-06`, `L12-15`).
 *
 * La DoD du lot tient en une phrase : « un screenshot Apple Fitness pré-remplit une course
 * en une action, et rien n'est écrit sans validation ». Les deux moitiés sont vérifiées
 * ici, et la seconde l'est en **comptant les écritures**, pas en regardant l'écran.
 */

import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Toaster } from '@/components/ui';
import { createQueryClient } from '@/lib/query';

import { Activity } from './Activity';

interface Call {
  url: string;
  init: RequestInit | undefined;
}

const calls: Call[] = [];

function json(status: number, body: unknown): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response;
}

const OVERVIEW = {
  week: {
    week_start: '2026-07-27',
    minutes: 0,
    sessions: 0,
    distance_km: 0,
    pace_min_km: null,
  },
  days: [],
  weeks: [],
  muscles: [],
  neglected: [],
  history: [],
  total: 0,
};

/** Ce qu'une capture d'Apple Fitness rend, une fois lue et convertie (`IMP-03`). */
const DRAFT = {
  kind: 'run',
  date: '2026-07-28',
  workout_type: 'Course à pied',
  distance_km: 8.369,
  duration_min: 44.2,
  avg_hr: 152,
  elevation_m: null,
  calories: 620,
  missing: ['elevation_m'],
  duplicate: null,
};

function stub(custom?: (url: string, init?: RequestInit) => Response | undefined) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = input as string;
    calls.push({ url, init });

    const override = custom?.(url, init);
    if (override) return Promise.resolve(override);

    if (url.includes('/api/ai/status')) {
      return Promise.resolve(json(200, { enabled: true, message: 'disponible' }));
    }
    if (url.includes('/api/import/apple/analyze')) return Promise.resolve(json(200, DRAFT));
    if (url.includes('/activity/progress')) return Promise.resolve(json(200, []));
    if (url.includes('/activity/exercises')) return Promise.resolve(json(200, []));
    if (url.includes('/activity/types')) return Promise.resolve(json(200, ['musculation']));
    if (url.includes('/activity/muscle-groups')) return Promise.resolve(json(200, ['dos']));
    if (url.endsWith('/api/activity')) return Promise.resolve(json(200, OVERVIEW));
    return Promise.resolve(json(200, {}));
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function renderActivity() {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter>
        <Toaster>
          <Activity />
        </Toaster>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** Choisit une capture, une fois la carte d'import affichée. */
async function chooseScreenshot() {
  await screen.findByText("Import d'une capture");
  const input = document.querySelector('#apple-screenshot') as HTMLInputElement;
  await userEvent.upload(input, new File(['png'], 'capture.png', { type: 'image/png' }));
}

/** Choisit une capture et la fait lire. */
async function readScreenshot() {
  await chooseScreenshot();
  await userEvent.click(screen.getByRole('button', { name: 'Lire la capture' }));
  await screen.findByText(/Les champs en pointillé/);
}

function writes(): Call[] {
  return calls.filter((call) => call.init?.method !== undefined && call.init.method !== 'GET');
}

/** La carte d'import, pour ne pas confondre ses champs avec ceux des formulaires manuels. */
function importCard(): HTMLElement {
  return screen.getByText("Import d'une capture").closest('div') as HTMLElement;
}

beforeEach(() => {
  calls.length = 0;
  URL.createObjectURL = vi.fn(() => 'blob:capture');
  URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('import Apple', () => {
  it("n'apparaît pas sans clé configurée", async () => {
    // `IA-07` : les deux formulaires manuels suffisent à tout, et une carte inerte à
    // chaque visite serait du bruit. L'état se lit dans Réglages.
    stub((url) =>
      url.includes('/api/ai/status')
        ? json(200, { enabled: false, message: 'pas de clé' })
        : undefined,
    );
    renderActivity();

    await screen.findByText('Nouvelle course');
    expect(screen.queryByText("Import d'une capture")).not.toBeInTheDocument();
  });

  it('ne lit rien tant qu’aucune capture n’est choisie', async () => {
    stub();
    renderActivity();

    await screen.findByText("Import d'une capture");
    expect(screen.queryByRole('button', { name: 'Lire la capture' })).not.toBeInTheDocument();
  });

  it('pré-remplit une course avec les valeurs converties', async () => {
    // La DoD : miles → km et `44:12` → décimal se font côté serveur, l'écran les affiche.
    stub();
    renderActivity();
    await readScreenshot();

    const card = importCard();
    expect(within(card).getByLabelText('Distance (km)')).toHaveValue('8,369');
    expect(within(card).getByLabelText('Durée (min)')).toHaveValue('44,2');
    expect(within(card).getByLabelText('FC moyenne')).toHaveValue('152');
    expect(within(card).getByLabelText('Date')).toHaveValue('2026-07-28');
  });

  it("n'écrit rien à la lecture de la capture", async () => {
    // `IMP-01` : l'endpoint analyse seulement. Entre lire et écrire, il y a un appui.
    stub();
    renderActivity();
    await readScreenshot();

    expect(writes().filter((call) => !call.url.includes('analyze'))).toHaveLength(0);
  });

  it('marque comme proposées les valeurs venues de la capture', async () => {
    stub();
    renderActivity();
    await readScreenshot();

    expect(within(importCard()).getByLabelText('Distance (km)')).toHaveAttribute(
      'aria-description',
      'valeur proposée, à valider',
    );
  });

  it('laisse vide et annonce ce que la capture ne portait pas', async () => {
    // `IMP-03` : une valeur absente reste absente, et l'écran le **dit**.
    stub();
    renderActivity();
    await readScreenshot();

    expect(within(importCard()).getByLabelText('Dénivelé (m)')).toHaveValue('');
    expect(screen.getByText(/le dénivelé/)).toBeInTheDocument();
    // Un champ vide et non marqué : il n'a été proposé par personne.
    expect(within(importCard()).getByLabelText('Dénivelé (m)')).not.toHaveAttribute(
      'aria-description',
    );
  });

  it('laisse corriger une valeur proposée au doigt', async () => {
    // `IMP-02` : intégralement modifiable. Une valeur qu'on ne peut pas retoucher est une
    // valeur qu'on adopte faute de mieux.
    stub();
    renderActivity();
    await readScreenshot();

    const card = importCard();
    await userEvent.click(within(card).getByRole('button', { name: 'FC moyenne : augmenter' }));

    expect(within(card).getByLabelText('FC moyenne')).toHaveValue('157');
    expect(within(card).getByLabelText('FC moyenne')).not.toHaveAttribute('aria-description');
  });

  it('écrit ce que l’utilisateur a validé, corrections comprises', async () => {
    stub((url, init) =>
      url.endsWith('/api/import/apple') && init?.method === 'POST'
        ? json(201, {
            kind: 'run',
            id: 0,
            date: '2026-07-28',
            label: 'Course à pied',
            duration_min: 44.2,
            distance_km: 8.369,
            source: 'apple',
          })
        : undefined,
    );
    renderActivity();
    await readScreenshot();

    const card = importCard();
    await userEvent.click(within(card).getByRole('button', { name: 'Distance (km) : augmenter' }));
    await userEvent.click(screen.getByRole('button', { name: 'Importer cette activité' }));

    await waitFor(() => {
      const posted = writes().find((call) => call.url.endsWith('/api/import/apple'));
      expect(posted).toBeDefined();
      // 8,369 + 0,5 arrondi à deux décimales : le pas-à-pas incrémente des dizaines de
      // mètres, pas des millimètres. La valeur **non touchée** garde sa précision.
      expect(JSON.parse(posted?.init?.body as string)).toMatchObject({
        kind: 'run',
        date: '2026-07-28',
        distance_km: '8,87',
        duration_min: '44,2',
      });
    });
  });

  it('jette le brouillon quand on n’est pas d’accord', async () => {
    stub();
    renderActivity();
    await readScreenshot();

    await userEvent.click(
      within(importCard()).getByRole('button', { name: /Pas d’accord|Pas d'accord/ }),
    );

    expect(screen.queryByLabelText('Distance (km)')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Lire la capture' })).toBeInTheDocument();
  });

  it('avertit d’un doublon probable sans rien bloquer', async () => {
    // `IMP-04` : un avertissement, jamais un refus. Deux sorties le même jour, cela existe.
    stub((url) =>
      url.includes('/api/import/apple/analyze')
        ? json(200, {
            ...DRAFT,
            duplicate: {
              kind: 'run',
              id: 3,
              date: '2026-07-28',
              label: 'Course de 8,40 km',
              duration_min: 44.2,
            },
          })
        : undefined,
    );
    renderActivity();
    await readScreenshot();

    expect(screen.getByText('doublon probable')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Importer cette activité' })).toBeEnabled();
  });

  it('dit ce qu’il faut faire d’une capture illisible', async () => {
    // `IMP-06` : le message vient du serveur et s'affiche tel quel.
    stub((url) =>
      url.includes('/api/import/apple/analyze')
        ? json(422, {
            code: 'ai_unreadable',
            message: 'Cette capture n’a pas pu être lue. Réessaie ou saisis à la main.',
          })
        : undefined,
    );
    renderActivity();
    await chooseScreenshot();
    await userEvent.click(screen.getByRole('button', { name: 'Lire la capture' }));

    expect(await screen.findByText(/Cette capture n’a pas pu être lue/)).toBeInTheDocument();
    // La capture reste choisie : relancer l'analyse est à un appui (`IMP-06`).
    expect(screen.getByRole('button', { name: 'Lire la capture' })).toBeInTheDocument();
    // Et la saisie manuelle n'a jamais bougé.
    expect(screen.getByRole('button', { name: 'Enregistrer la course' })).toBeInTheDocument();
  });

  it('refuse d’importer tant que la date manque', async () => {
    // Deviner la date d'une activité serait faire entrer une mesure fausse dans le fichier.
    stub((url) =>
      url.includes('/api/import/apple/analyze')
        ? json(200, { ...DRAFT, date: null, missing: ['date', 'elevation_m'] })
        : undefined,
    );
    renderActivity();
    await readScreenshot();

    expect(screen.getByRole('button', { name: 'Importer cette activité' })).toBeDisabled();
    expect(screen.getByText(/La date et la durée manquent/)).toBeInTheDocument();
  });

  it('permet de basculer une course en séance', async () => {
    // Le brouillon propose, il n'impose pas — y compris sur la nature de l'activité.
    stub();
    renderActivity();
    await readScreenshot();

    await userEvent.click(within(importCard()).getByRole('button', { name: 'Séance' }));

    // Une séance n'a pas de distance : le champ disparaît au lieu d'être ignoré.
    expect(within(importCard()).queryByLabelText('Distance (km)')).not.toBeInTheDocument();
  });
});
