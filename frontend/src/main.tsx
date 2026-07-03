import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import VariantA from './demo/variant-a/VariantA';
import './index.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <VariantA />
  </StrictMode>,
);
