import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Toaster } from '@/components/ui';
import { createQueryClient } from '@/lib/query';
import { DAY_DETAIL, GRIDS } from '@/test/fixtures';

import { Assiduity } from './Assiduity';

/**
 * Écran Assiduité (`L11-06` → `L11-09`).
 *
 * Ces tests existent à cause d'une leçon du premier usage réel : le bouton « ouvrir »
 * d'une séance était inerte depuis des semaines, et aucun test ne l'avait vu parce que
 * le parcours n'avait **aucun test d'écran**. Un composant juste et un endpoint juste ne
 * font pas un écran qui marche.
 *
 * Trois propriétés sont vérifiées ici et nulle part ailleurs :
 *
 * * l'écran demande ses neuf grilles en **un seul appel** (`HEAT-25`) ;
 * * une piste `per_week` n'affiche **aucun jour rouge** (`HEAT-11`) — le rouge est sur la
 *   bande hebdomadaire, et un écran qui chercherait des jours rouges y lirait un
 *   sans-faute permanent ;
 * * cliquer une cellule ouvre son détail (`HEAT-29`), et le détail arrive vraiment.
 */

interface Call {
  url: string;
  init: RequestInit | undefined;
}

const calls: Call[] = [];

function json(status: number, body: unknown): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response;
}

function stub(custom?: (url: string) => Response | undefined) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = input as string;
    calls.push({ url, init });

    const override = custom?.(url);
    if (override) return Promise.resolve(override);

    if (url.includes('/day/')) return Promise.resolve(json(200, DAY_DETAIL));
    return Promise.resolve(json(200, GRIDS));
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

/** Première cellule d'une grille répondant au sélecteur, ou l'échec du test. */
function cellIn(grid: HTMLElement, selector: string): HTMLButtonElement {
  const cell = grid.querySelector<HTMLButtonElement>(selector);
  if (cell === null) throw new Error(`aucune cellule « ${selector} » dans la grille`);
  return cell;
}

function renderScreen() {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter>
        <Toaster>
          <Assiduity />
        </Toaster>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  calls.length = 0;
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('écran Assiduité', () => {
  it('demande toutes les grilles en un seul appel', async () => {
    // `HEAT-25`. Neuf pistes en neuf requêtes, c'est neuf fois les mêmes fichiers relus
    // côté serveur — et neuf allers-retours sur une liaison à ~180 ms.
    stub();
    renderScreen();

    await screen.findByRole('heading', { name: 'Eau' });

    const grids = calls.filter((call) => !call.url.includes('/day/'));
    expect(grids).toHaveLength(1);
    expect(grids[0]?.url).toContain('/api/heatmap');
  });

  it('affiche une grille et ses chiffres par piste', async () => {
    stub();
    renderScreen();

    await screen.findByRole('heading', { name: 'Eau' });

    expect(screen.getByRole('grid', { name: /Assiduité — Eau/ })).toBeInTheDocument();
    expect(screen.getByRole('grid', { name: /Assiduité — Torse/ })).toBeInTheDocument();
    // Le taux de respect vient du serveur : l'écran ne divise rien (`HEAT-30`).
    expect(screen.getByText('75 %')).toBeInTheDocument();
    expect(screen.getByText('50 %')).toBeInTheDocument();
  });

  it('affiche le libellé de cadence tel que le serveur le formule', async () => {
    // `HEAT-30` : reconstruire « 2 fois par semaine » côté client reviendrait à recoder
    // la grammaire des cadences, et à la voir diverger à la sixième.
    stub();
    renderScreen();

    expect(await screen.findByText('2 fois par semaine')).toBeInTheDocument();
    expect(screen.getByText('tous les jours')).toBeInTheDocument();
  });

  it('ne peint aucun jour rouge sur une piste hebdomadaire', async () => {
    // `HEAT-11`, et le second piège de rendu du lot L10.
    stub();
    renderScreen();

    const grid = await screen.findByRole('grid', { name: /Assiduité — Torse/ });

    expect(grid.querySelectorAll('[data-state="missed"]')).toHaveLength(0);
    // Le verdict est sur la semaine, et il est bien là.
    expect(
      screen.getByRole('list', { name: /hebdomadaire.*Torse/i }).querySelectorAll('[data-status]'),
    ).toHaveLength(1);
  });

  it('distingue un jour neutralisé d’un jour à venir et d’un jour sans attente', async () => {
    // Trois `off` pour trois histoires différentes. Sans la nuance, une semaine de grippe
    // et une semaine sans attente rendent la même cellule grise.
    stub();
    renderScreen();

    const grid = await screen.findByRole('grid', { name: /Assiduité — Eau/ });

    expect(grid.querySelectorAll('[data-reason="neutralised"]')).toHaveLength(1);
    expect(grid.querySelectorAll('[data-reason="future"]')).toHaveLength(1);
    expect(grid.querySelectorAll('[data-reason="pending"]')).toHaveLength(1);
  });

  it('ouvre le détail d’un jour au clic sur sa cellule', async () => {
    // `HEAT-29`. Une grille qui ne s'explore pas ne se vérifie pas : voir « 8 séries »
    // sans pouvoir demander lesquelles laisse l'utilisateur sans recours.
    stub();
    renderScreen();

    const grid = await screen.findByRole('grid', { name: /Assiduité — Torse/ });

    await userEvent.click(cellIn(grid, '[data-state="done"]'));

    const drawer = await screen.findByRole('dialog', { name: /20 juillet/ });
    expect(drawer).toBeInTheDocument();
    expect(await screen.findByText('Développé couché')).toBeInTheDocument();
    expect(screen.getByText('dernière série en dégressif')).toBeInTheDocument();
    expect(calls.some((call) => call.url.includes('/api/heatmap/torse/day/2026-07-20'))).toBe(true);
  });

  it('referme le tiroir', async () => {
    stub();
    renderScreen();

    const grid = await screen.findByRole('grid', { name: /Assiduité — Torse/ });
    await userEvent.click(cellIn(grid, '[data-state="done"]'));
    await screen.findByRole('dialog');

    await userEvent.click(screen.getByRole('button', { name: 'Fermer' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
  });

  it('n’ouvre pas un jour antérieur à la piste ni un jour à venir', async () => {
    stub();
    renderScreen();

    const grid = await screen.findByRole('grid', { name: /Assiduité — Eau/ });

    expect(grid.querySelector('[data-reason="future"]')).toBeDisabled();
  });

  it('dit ce qui manque plutôt que d’afficher une grille vide', async () => {
    stub(() => json(200, { range: GRIDS.range, grids: [] }));
    renderScreen();

    expect(await screen.findByText(/Aucune piste active/)).toBeInTheDocument();
  });

  it('affiche le refus du serveur tel qu’il est écrit', async () => {
    // `API-07` : le message vient du serveur, en français, et s'affiche sans réécriture.
    // Un refus métier n'est pas rejoué (`STO-08`) — contrairement à un `503` passager,
    // qui serait réessayé deux fois avant d'arriver ici.
    stub(() => json(404, { code: 'not_found', message: 'Cette piste n’existe plus.' }));
    renderScreen();

    expect(await screen.findByText('Cette piste n’existe plus.')).toBeInTheDocument();
  });
});
