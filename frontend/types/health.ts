// Mirrors backend/app/schemas/health.py
export interface HealthResponse {
  status: string;
  app: string;
  version: string;
  demo_mode: boolean;
  integrations: Record<string, boolean>;
}
