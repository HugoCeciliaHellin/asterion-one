/**
 * Asterion One — Ground Control UI
 * =================================
 * Reference: Art.5 §3.2.5 — ground_ui (5 views)
 *
 * Views (implemented in Phase 3):
 *   /pass-planner   → PassPlannerView   [REQ-GND-PLAN]
 *   /live-health    → LiveHealthView    [REQ-OPS-OBSERVABILITY]
 *   /alerts         → AlertDashboardView [REQ-DT-RATIONALE]
 *   /timeline       → AuditTimelineView [REQ-FSW-LOG-SECURE]
 *   /twin-insights  → TwinInsightsView  [REQ-DT-EARLY-15m]
 */

import React from 'react';
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom';

// Placeholder views — replaced in Phase 3
const Placeholder = ({ name }) => (
  <div style={{ padding: '2rem' }}>
    <h2>{name}</h2>
    <p>This view will be implemented in Phase 3.</p>
  </div>
);

const PassPlannerView = () => <Placeholder name="Pass Planner" />;
const LiveHealthView = () => <Placeholder name="Live Health" />;
const AlertDashboardView = () => <Placeholder name="Alert Dashboard" />;
const AuditTimelineView = () => <Placeholder name="Audit Timeline" />;
const TwinInsightsView = () => <Placeholder name="Twin Insights" />;

const navStyle = {
  display: 'flex',
  gap: '1rem',
  padding: '1rem',
  background: '#1a1a2e',
  borderBottom: '2px solid #16213e',
};

const linkStyle = {
  color: '#e0e0e0',
  textDecoration: 'none',
  padding: '0.5rem 1rem',
  borderRadius: '4px',
  fontSize: '0.9rem',
};

const activeLinkStyle = {
  ...linkStyle,
  background: '#0f3460',
  color: '#00d2ff',
};

export default function App() {
  return (
    <BrowserRouter>
      <nav style={navStyle}>
        <span style={{ color: '#00d2ff', fontWeight: 'bold', marginRight: '1rem' }}>
          ✦ ASTERION ONE
        </span>
        <NavLink to="/pass-planner" style={({ isActive }) => isActive ? activeLinkStyle : linkStyle}>
          Pass Planner
        </NavLink>
        <NavLink to="/live-health" style={({ isActive }) => isActive ? activeLinkStyle : linkStyle}>
          Live Health
        </NavLink>
        <NavLink to="/alerts" style={({ isActive }) => isActive ? activeLinkStyle : linkStyle}>
          Alerts
        </NavLink>
        <NavLink to="/timeline" style={({ isActive }) => isActive ? activeLinkStyle : linkStyle}>
          Timeline
        </NavLink>
        <NavLink to="/twin-insights" style={({ isActive }) => isActive ? activeLinkStyle : linkStyle}>
          Twin Insights
        </NavLink>
      </nav>

      <Routes>
        <Route path="/" element={<PassPlannerView />} />
        <Route path="/pass-planner" element={<PassPlannerView />} />
        <Route path="/live-health" element={<LiveHealthView />} />
        <Route path="/alerts" element={<AlertDashboardView />} />
        <Route path="/timeline" element={<AuditTimelineView />} />
        <Route path="/twin-insights" element={<TwinInsightsView />} />
      </Routes>
    </BrowserRouter>
  );
}
