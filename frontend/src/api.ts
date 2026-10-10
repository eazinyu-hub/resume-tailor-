// An empty value uses Vite's local /api proxy; an explicit URL supports other setups.
export const API_BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
