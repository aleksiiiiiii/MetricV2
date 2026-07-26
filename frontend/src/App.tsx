import { Route, Routes } from 'react-router';

import { Home } from '@/routes/Home';
import { KitchenSink } from '@/routes/KitchenSink';

/**
 * Table de routage. La coquille applicative — navigation, en-tête, routes protégées —
 * est construite au lot L03 ; on ne câble ici que le minimum qui prouve que le
 * routage, les styles et le proxy fonctionnent.
 */
export function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/_kitchen-sink" element={<KitchenSink />} />
      <Route path="*" element={<Home />} />
    </Routes>
  );
}
