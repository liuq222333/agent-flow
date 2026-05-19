-- Seed DeepSeek as a default OpenAI-compatible chat provider option.

INSERT INTO model_providers (name, provider_type, base_url, status, config_json)
VALUES
  (
    'deepseek',
    'deepseek',
    'https://api.deepseek.com',
    'active',
    '{"api_key_secret": "deepseek_api_key"}'::jsonb
  )
ON CONFLICT (name) DO UPDATE
SET provider_type = EXCLUDED.provider_type,
    base_url = EXCLUDED.base_url,
    config_json = EXCLUDED.config_json,
    updated_at = now();

INSERT INTO model_configs (
  provider_id,
  model_name,
  model_type,
  display_name,
  context_window,
  default_config_json,
  status
)
SELECT
  p.id,
  'deepseek-v4-flash',
  'chat',
  'DeepSeek V4-Flash',
  1000000,
  '{"temperature": 0.3, "max_tokens": 1000, "model_version": "DeepSeek-V4-Flash", "api_model_alias": "deepseek-v4-flash", "thinking_mode": false}'::jsonb,
  'active'
FROM model_providers p
WHERE p.name = 'deepseek'
ON CONFLICT (provider_id, model_name) DO UPDATE
SET model_type = EXCLUDED.model_type,
    display_name = EXCLUDED.display_name,
    context_window = EXCLUDED.context_window,
    default_config_json = EXCLUDED.default_config_json,
    status = EXCLUDED.status,
    updated_at = now();
