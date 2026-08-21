/**
 * La lecture du jour, sur l'écran d'accueil.
 *
 * ## Ce qu'elle est, et pourquoi elle porte le vocabulaire existant
 *
 * Un message écrit par le modèle, posé à côté de mesures réelles. C'est exactement ce que
 * l'invariant « une valeur proposée n'est pas une mesure » vise, et le projet n'a que deux
 * façons de le dire — `AiBlock` et l'état `proposed` du `Stepper`. Aucune troisième n'est
 * inventée ici : c'est le même `AiBlock` que `/nutrition`, `/activite`, `/planning` et
 * `/objectif`, avec la conduite en plus qu'a demandé la charte.
 *
 * `GuidelinesUI.html` §10 « Lecture assistée » dessine cette carte depuis le premier jour :
 * bloc IA, tag daté, un paragraphe court dont les chiffres sont en gras, des boutons
 * dessous. Elle n'avait simplement jamais été implémentée.
 *
 * ## Un second appel, et pourquoi il ne casse pas `AGG-01`
 *
 * `AGG-01` promet **les indicateurs** de l'écran d'accueil en une requête, et cela reste
 * vrai : le tableau de bord peint entièrement sans attendre celle-ci. La lecture est une
 * surface indépendante, avec ses propres quatre états — et l'attendre pour dessiner les
 * chiffres aurait fait payer à tout l'écran la latence d'un modèle.
 *
 * ## Les quatre états, et le cinquième qui n'en est pas un
 *
 * Chargement, absente, erreur, écrite. **L'IA indisponible n'est pas un état de cette
 * carte : c'est son absence.** Un bouton mort et une phrase d'explication sur l'écran
 * qu'on ouvre le plus seraient le contraire de ce que promet `IA-07` — l'assistance est un
 * confort, jamais un prérequis, et un confort absent ne se commente pas.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router';

import { AiBlock, Button, LinkButton, Markdown } from '@/components/ui';
import { briefApi } from '@/features/brief/api';
import { useAiStatus } from '@/features/ai/useAiStatus';
import { ApiError } from '@/lib/api';
import { longDate, plural } from '@/lib/format';
import { keys } from '@/lib/query';
import { useToast } from '@/lib/toast';

import styles from '../Dashboard.module.css';

/** « Lecture du mercredi 19 août ». Le jour vient du serveur, jamais de l'horloge locale. */
function tagFor(day: string): string {
  return `Lecture du ${longDate(`${day}T12:00:00`)}`;
}

export function Brief() {
  const navigate = useNavigate();
  const client = useQueryClient();
  const { notify } = useToast();
  const ai = useAiStatus();

  const { data, isPending, error, refetch } = useQuery({
    queryKey: keys.brief.today(),
    queryFn: briefApi.read,
    // Sans clé OpenRouter, il n'y a rien à lire et rien à proposer : la requête ne part
    // pas plutôt que de rendre un « absent » qu'on ne saurait pas quoi faire.
    enabled: ai.enabled,
  });

  /** Demande la lecture au modèle. Repli de l'ordonnanceur, jamais automatique. */
  const ask = useMutation({
    mutationFn: briefApi.write,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.brief.all() });
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Lecture impossible.', 'recover');
    },
  });

  /**
   * Ouvre le fil et y entre.
   *
   * Le fil est **semé côté serveur** : son premier message est celui de l'assistant. Poser
   * le texte dans le champ de saisie aurait fait répondre le modèle à une phrase qu'il ne
   * se souvient pas d'avoir écrite — elle ne serait pas dans l'historique du fil.
   */
  const open = useMutation({
    mutationFn: briefApi.openThread,
    onSuccess: (thread) => {
      void client.invalidateQueries({ queryKey: keys.brief.all() });
      void client.invalidateQueries({ queryKey: keys.assistant.threads() });
      void navigate(`/assistant?fil=${encodeURIComponent(thread.thread_id)}`);
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Ouverture impossible.', 'recover');
    },
  });

  // `pending` n'est pas `indisponible` : sans cette garde, la carte disparaîtrait le temps
  // d'un aller-retour puis réapparaîtrait, ce qui déplace tout l'écran sous les yeux.
  if (ai.pending) return null;
  if (!ai.enabled) return null;

  /**
   * La porte de côté — **et elle n'apparaît que face à une lecture**.
   *
   * C'est ce que demande le lot : le corps du bloc mène *dedans*, ce bouton mène *à
   * côté*. Le libellé le dit, plutôt que de répéter « Ouvrir l'assistant » sur deux
   * cibles qui ne font pas la même chose.
   *
   * Sans lecture, il n'y a rien à ne pas emporter : le bouton disparaît, et la rangée de
   * portes en pied d'écran — qui existe de toute façon, y compris sans clé OpenRouter —
   * reste la seule entrée. Deux liens « Ouvrir l'assistant » sur un même écran auraient
   * été deux fois le même geste, à deux endroits.
   */
  const aside = (
    <LinkButton variant="ghost" to="/assistant">
      Ouvrir sans ce message
    </LinkButton>
  );

  if (isPending) {
    return (
      <AiBlock tag="Lecture du jour">
        <p className={styles.briefLoading}>lecture en cours d’écriture…</p>
      </AiBlock>
    );
  }

  if (error) {
    return (
      <AiBlock
        tag="Lecture du jour"
        actions={
          <>
            <Button
              variant="ghost"
              onClick={() => {
                void refetch();
              }}
            >
              Réessayer
            </Button>
          </>
        }
      >
        {/* Le message vient du serveur, en français, et s'affiche tel quel (`API-07`). */}
        <p>{error instanceof Error ? error.message : 'Le serveur n’a pas répondu.'}</p>
      </AiBlock>
    );
  }

  if (data.state === 'absent') {
    return (
      <AiBlock
        tag="Lecture du jour"
        actions={
          <>
            <Button
              variant="primary"
              busy={ask.isPending}
              className={styles.briefAsk}
              onClick={() => {
                ask.mutate();
              }}
            >
              Demander la lecture
            </Button>
          </>
        }
      >
        {/* Un état vide dit ce que coûte le prochain geste, et n'affiche aucune valeur
            inventée. Surtout pas une phrase d'encouragement générique : ce serait
            exactement le compliment sans chiffre que la consigne interdit au modèle. */}
        <p>
          Rien n’est encore écrit pour aujourd’hui. Elle s’écrit toute seule dans la matinée — ou
          maintenant, si tu la demandes.
        </p>
      </AiBlock>
    );
  }

  return (
    <AiBlock
      tag={tagFor(data.day)}
      onOpen={() => {
        open.mutate();
      }}
      hint={open.isPending ? 'ouverture…' : 'Répondre à ce message →'}
      label="Répondre à la lecture du jour dans l’assistant"
      actions={aside}
    >
      <div className={styles.briefText}>
        {/* Les chiffres arrivent en gras — c'est la forme que la charte donne à cette
            carte, et la consigne du serveur la demande explicitement. Aucun HTML n'est
            injecté : `Markdown` construit des nœuds React depuis une fonction pure. */}
        <Markdown>{data.message}</Markdown>
      </div>

      {/* Le condensé réellement envoyé, replié. C'est la seule façon de vérifier à l'écran
          que les fichiers n'ont pas été envoyés entiers (`IA-09`) — la même promesse que
          sous chaque réponse de l'assistant, tenue de la même façon. */}
      {data.basis.length > 0 && (
        <details className={styles.facts}>
          <summary>
            Ce qui a été envoyé ({data.basis.length} {plural(data.basis.length, 'ligne')}, aucun
            fichier)
          </summary>
          <ul>
            {data.basis.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </details>
      )}
    </AiBlock>
  );
}
