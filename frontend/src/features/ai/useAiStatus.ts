/**
 * Disponibilité de l'assistance, pour les écrans qui en proposent (`IA-07`).
 *
 * Deux décisions :
 *
 * * **Jamais rejoué.** Une clé s'ajoute dans `.env` et demande un redémarrage du serveur :
 *   la réponse ne peut pas changer pendant une session. La redemander à chaque écran
 *   coûterait un aller-retour pour une valeur constante.
 * * **Un échec vaut « indisponible », pas une erreur d'écran.** Si cette requête échoue,
 *   l'écran se contente de ne rien proposer — il ne s'interrompt pas. C'est exactement la
 *   promesse de `IA-07` : l'IA est un confort, jamais un prérequis.
 * * **« On ne sait pas encore » n'est pas « indisponible ».** `pending` existe pour ça :
 *   sans lui, `enabled` vaut `false` pendant le chargement et un écran affiche
 *   « assistance indisponible » avant d'avoir posé la question. C'est la même faute que
 *   d'écrire « aucune pesée » avant d'avoir lu l'historique.
 */

import { useQuery } from '@tanstack/react-query';

import { aiApi } from '@/features/ai/api';
import { keys } from '@/lib/query';

export function useAiStatus(): { enabled: boolean; pending: boolean; message: string } {
  const { data, isPending } = useQuery({
    queryKey: keys.ai.status(),
    queryFn: aiApi.status,
    staleTime: Infinity,
    retry: false,
  });

  return {
    enabled: data?.enabled ?? false,
    pending: isPending,
    message: data?.message ?? '',
  };
}
