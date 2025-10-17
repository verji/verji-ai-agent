use anyhow::{Context, Result};
use matrix_sdk::{
    authentication::matrix::MatrixSession,
    Client,
};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use tracing::{info, warn};

/// Client configuration for persistence
#[derive(Debug, Serialize, Deserialize)]
pub struct ClientSession {
    pub homeserver: String,
    pub db_path: String,
}

/// Full session data that we persist to disk
#[derive(Debug, Serialize, Deserialize)]
pub struct FullSession {
    pub client_session: ClientSession,
    pub user_session: MatrixSession,
}

/// Load session from file
pub async fn load_session(session_file: &PathBuf) -> Result<FullSession> {
    let data = tokio::fs::read_to_string(session_file).await?;
    let session: FullSession = serde_json::from_str(&data)?;
    Ok(session)
}

/// Save session to file
pub async fn save_session(session_file: &PathBuf, full_session: &FullSession) -> Result<()> {
    let data = serde_json::to_string_pretty(full_session)?;
    tokio::fs::write(session_file, data).await?;
    Ok(())
}

/// Save current client session to file
pub async fn save_client_session(
    client: &Client,
    session_file: &PathBuf,
    homeserver: &str,
    store_path: &str,
) -> Result<()> {
    use matrix_sdk::AuthSession;

    if let Some(AuthSession::Matrix(matrix_session)) = client.session() {
        let full_session = FullSession {
            client_session: ClientSession {
                homeserver: homeserver.to_string(),
                db_path: store_path.to_string(),
            },
            user_session: matrix_session,
        };

        match save_session(session_file, &full_session).await {
            Ok(_) => {
                info!("✅ Session saved to: {:?}", session_file);
                Ok(())
            }
            Err(e) => {
                warn!("⚠️  Failed to save session: {}", e);
                Err(e).context("Failed to save session")
            }
        }
    } else {
        Err(anyhow::anyhow!("No active Matrix session to save"))
    }
}
