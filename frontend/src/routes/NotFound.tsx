import { useNavigate } from 'react-router';

import { Button, Empty } from '@/components/ui';

export function NotFound() {
  const navigate = useNavigate();

  return (
    <div className="wrap">
      <Empty
        title="Page introuvable"
        action={
          <Button
            variant="primary"
            onClick={() => {
              void navigate('/');
            }}
          >
            Retour au tableau de bord
          </Button>
        }
      >
        Cette adresse ne correspond à aucun écran de Metric.
      </Empty>
    </div>
  );
}
