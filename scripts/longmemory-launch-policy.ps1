# LongMemory is a separate Node process. Keep inherited model-provider
# credentials and selectors out of the supported local launcher by default.
$script:LongMemoryProviderEnvironmentVariables = @(
  'LONGMEMORY_EMBEDDING_PROVIDER', 'OM_EMBEDDINGS',
  'LONGMEMORY_EMBEDDING_FALLBACK', 'OM_EMBEDDING_FALLBACK',
  'OPENAI_API_KEY', 'OM_OPENAI_API_KEY',
  'LONGMEMORY_OPENAI_BASE_URL', 'OM_OPENAI_BASE_URL',
  'GEMINI_API_KEY', 'OM_GEMINI_API_KEY',
  'LONGMEMORY_GEMINI_BASE_URL', 'OM_GEMINI_BASE_URL',
  'NVIDIA_API_KEY', 'LONGMEMORY_NVIDIA_BASE_URL',
  'SIRAY_API_TOKEN', 'OM_SIRAY_API_TOKEN',
  'LONGMEMORY_SIRAY_BASE_URL', 'OM_SIRAY_BASE_URL',
  'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN',
  'AWS_PROFILE', 'AWS_REGION', 'AWS_DEFAULT_REGION', 'AWS_ROLE_ARN',
  'AWS_WEB_IDENTITY_TOKEN_FILE', 'AWS_CONTAINER_CREDENTIALS_FULL_URI',
  'AWS_CONTAINER_CREDENTIALS_RELATIVE_URI', 'AWS_ENDPOINT_URL',
  'AWS_ENDPOINT_URL_BEDROCK', 'AWS_CONFIG_FILE', 'AWS_SHARED_CREDENTIALS_FILE',
  'LONGMEMORY_AWS_EMBEDDING_MODEL', 'OM_AWS_MODEL',
  'LONGMEMORY_OLLAMA_URL', 'OLLAMA_URL', 'OM_OLLAMA_URL',
  'LONGMEMORY_LOCAL_EMBEDDING_URL', 'OM_LOCAL_MODEL_URL'
)

function Invoke-LongMemoryWithRemoteProvidersDisabled {
  param(
    [Parameter(Mandatory = $true)]
    [scriptblock] $Action
  )

  $saved = @{}
  foreach ($name in $script:LongMemoryProviderEnvironmentVariables) {
    $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
    [Environment]::SetEnvironmentVariable($name, $null, 'Process')
  }

  try {
    & $Action
  }
  finally {
    foreach ($name in $script:LongMemoryProviderEnvironmentVariables) {
      [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process')
    }
  }
}
