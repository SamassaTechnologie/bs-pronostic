export type Team = { id: number; name: string };
export type Competition = { id: number; code: string; name: string; country: string };

export type MatchSummary = {
  id: number;
  kickoff: string;
  status: string;
  season: string | null;
  competition: Competition;
  home: Team;
  away: Team;
  score: { home: number; away: number; ht_home: number | null; ht_away: number | null } | null;
};

export type Confidence = { score: number; level: string; components?: { key: string; label: string; value: number }[]; notes?: string[] };

export type PickCard = {
  match: MatchSummary;
  market_key: string;
  label: string;
  short: string;
  family: string;
  family_label: string;
  probability: number;
  tier: string;
  confidence: Confidence;
  odds: number | null;
  bookmaker: string | null;
  implied_probability: number | null;
  edge: number | null;
  fair_odds: number | null;
  explanation: string;
  factors_for: string[];
  factors_against: string[];
  score: number | null;
  is_pick: boolean;
};

export type Market = {
  key: string;
  label: string;
  short: string;
  family: string;
  group: string;
  available: boolean;
  probability: number | null;
  raw_probability?: number;
  reason?: string;
  tier?: string;
  confidence?: Confidence;
  odds?: number | null;
  bookmaker?: string | null;
  implied_probability?: number | null;
  edge?: number | null;
  fair_odds?: number;
  explanation?: string;
  factors_for?: string[];
  factors_against?: string[];
};

export type FormBlock = {
  played: number;
  sequence?: string;
  points_per_match?: number;
  goals_for_avg?: number;
  goals_against_avg?: number;
  over25_rate?: number;
  btts_rate?: number;
  clean_sheets?: number;
  failed_to_score?: number;
  corners_for_avg?: number;
  corners_total_avg?: number;
  cards_total_avg?: number;
};

export type Analysis = {
  status: string;
  reasons: string[];
  markets: Market[];
  picks: string[];
  avoid_reasons?: string[];
  expected_goals?: { home: number; away: number };
  expected_ht_goals?: { home: number; away: number } | null;
  expected_corners?: { home: number; away: number } | null;
  expected_cards?: { home: number; away: number } | null;
  top_scores?: { score: string; probability: number }[];
  form: { home: Record<string, FormBlock>; away: Record<string, FormBlock> };
  h2h: { n: number; home_team_wins?: number; away_team_wins?: number; draws?: number; avg_total_goals?: number; over25_rate?: number; btts_rate?: number; matches: { date: string; home_id: number; away_id: number; score: string }[] };
  standings: { home: { position: number; points: number; played: number } | null; away: { position: number; points: number; played: number } | null; teams: number } | null;
  injuries: { home: { player: string; type: string; reason: string }[]; away: { player: string; type: string; reason: string }[] } | null;
  data_quality: { league_matches: number; home_matches: number; away_matches: number; limits: string[]; odds_markets: string[] };
  league?: Record<string, number | null>;
  match_confidence?: number;
  calibration?: { source: string; generated_at: string | null };
};

export type Provider = {
  name: string;
  label: string;
  website: string;
  requires_key: boolean;
  configured: boolean;
  enabled: boolean;
  capabilities: string[];
  setup: string;
  last_run: { kind: string; status: string; message: string | null; started_at: string; finished_at: string | null } | null;
  last_ok: string | null;
  requests_today: number;
};

export type Meta = {
  app: { name: string; slogan: string; engine: string };
  last_sync: string | null;
  last_analysis: string | null;
  providers: Provider[];
  competitions: Competition[];
  markets: { key: string; label: string; short: string; family: string; family_label: string }[];
  settings: Record<string, number>;
  calibration: {
    source: string | null;
    generated_at: string | null;
    n_matches: number | null;
    period: { start: string; split: string; end: string } | null;
    divisions: string[] | null;
    tiers: Record<string, { n: number; mean_predicted: number; observed_frequency: number }> | null;
    market_benchmark: Record<string, { n: number; brier_model: number; brier_market: number; logloss_model: number; logloss_market: number }> | null;
  };
  default_timezone: string;
  disclaimer: string;
};

export type GroupStat = {
  key: string | number;
  label: string;
  n: number;
  won: number;
  lost: number;
  hit_rate: number | null;
  avg_probability: number | null;
  gap: number | null;
  staked: number;
  profit: number;
  roi: number | null;
};

export type Performance = {
  overall: GroupStat & { total: number; pending: number; void: number; unverifiable: number };
  calibration: { brier: number | null; log_loss: number | null; table: { low: number; high: number; n: number; mean_predicted: number | null; observed_frequency: number | null }[] };
  by_market: GroupStat[];
  by_family: GroupStat[];
  by_competition: GroupStat[];
  by_tier: GroupStat[];
  by_confidence: GroupStat[];
  timeline: { date: string; n: number; hit_rate: number; profit: number }[];
  stake_rule: string;
};

export type HistoryRow = {
  id: number;
  created_at: string;
  match: MatchSummary;
  market_key: string;
  market_label: string;
  probability: number;
  confidence: number;
  confidence_level: string;
  tier: string;
  odds: number | null;
  result: string;
};

export type ComboLeg = { match_id: number; market_key: string; label: string; probability: number; confidence: number; odds: number | null; match_label: string; competition: string; kickoff: string; tier: string };
export type Combo = {
  valid: boolean;
  legs: ComboLeg[];
  n_legs?: number;
  probability?: number;
  fair_odds?: number | null;
  total_odds?: number | null;
  expected_value?: number | null;
  risk?: string;
  too_risky?: boolean;
  independent?: boolean;
  warnings: string[];
  errors: string[];
};
