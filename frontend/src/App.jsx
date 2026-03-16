/**
 * Root application component.
 * Routes are added here as each sprint delivers new pages.
 */
import { Routes, Route } from 'react-router-dom';

function App() {
  return (
    <Routes>
      {/* Routes added sprint by sprint — see ROADMAP.md */}
      <Route path="/" element={<div>Fieldmouse — coming soon</div>} />
    </Routes>
  );
}

export default App;
