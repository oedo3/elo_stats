import React, { useState } from 'react';
import axios from 'axios';
import './components/App.css';

function App() {
  const [playerName, setPlayerName] = useState('');
  const [playerStats, setPlayerStats] = useState(null);
  const [error, setError] = useState(null);

  const fetchStats = async () => {
    try {
      const response = await axios.get(`http://localhost:5000/api/player-stats?name=${playerName}`);
      setPlayerStats(response.data);
      setError(null);
    } catch (err) {
      setError('Player not found or server error.');
      setPlayerStats(null);
    }
  };

  return (
    <div className="container">
      <div className="sidebar">
        <div className="refresh-icon">🔄</div>
        <div className="date-display">Date<br />00/00/0000</div>

      </div>

      <div className="main-content">
        <div className="header">ELO Stats</div>
        <div className="search-bar">
          <input
            type="text"
            placeholder="Search for a player"
            value={playerName}
            onChange={(e) => setPlayerName(e.target.value)}
          />
          <button onClick={fetchStats}>🔍</button>
        </div>

        {error && <div className="error-message">{error}</div>}

        {playerStats && (
          <div className="player-section">
            <div className="profile">
              <div className="avatar">👤</div>
              <div className="player-info">
                <p>{playerStats.name}</p>
                <p>Position: TBD</p>
                <p>Height: TBD</p>
                <p>Weight: TBD</p>
              </div>
              <div className="jersey">{playerStats.jersey || '00'}</div>
              <div className="elo-score">ELO: {playerStats.elo}</div>
            </div>

            <div className="stats-grid">
              <p>G | Career | PTS | TRB | AST | FG% | FG3% | FT% | eFG% | PER | WS</p>
            </div>

            <div className="graph-placeholder">
              <div className="graph">(Graph Coming Soon)</div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default App;