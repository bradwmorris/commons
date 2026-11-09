//! Bounded admission for CPU-heavy validation. Never block Tokio's request workers.
use crate::{Result, fail};
use axum::http::StatusCode;
use tokio::sync::Semaphore;

static SLOTS: Semaphore = Semaphore::const_new(2);

pub async fn run<T: Send + 'static>(
    work: impl FnOnce() -> Result<T> + Send + 'static,
) -> Result<T> {
    let permit = SLOTS.try_acquire().map_err(|_| {
        fail(
            StatusCode::SERVICE_UNAVAILABLE,
            "validation busy; retry later",
        )
    })?;
    tokio::task::spawn_blocking(move || {
        // Keep admission until CPU work finishes, even if the HTTP caller disconnects.
        let _permit = permit;
        work()
    })
    .await
    .map_err(|_| fail(StatusCode::INTERNAL_SERVER_ERROR, "validation failed"))?
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn cancellation_keeps_admission_until_cpu_work_finishes() {
        let (started_tx, mut started_rx) = tokio::sync::mpsc::unbounded_channel();
        let mut jobs = Vec::new();
        let mut releases = Vec::new();
        for _ in 0..2 {
            let started = started_tx.clone();
            let (release, wait) = std::sync::mpsc::channel();
            releases.push(release);
            jobs.push(tokio::spawn(run(move || {
                started.send(()).unwrap();
                wait.recv().unwrap();
                Ok(())
            })));
        }
        for _ in 0..2 {
            tokio::time::timeout(std::time::Duration::from_secs(5), started_rx.recv())
                .await
                .unwrap()
                .unwrap();
        }
        assert!(matches!(
            run(|| Ok(())).await,
            Err(crate::error::Error(StatusCode::SERVICE_UNAVAILABLE, _))
        ));
        jobs[0].abort();
        assert!(matches!(
            run(|| Ok(())).await,
            Err(crate::error::Error(StatusCode::SERVICE_UNAVAILABLE, _))
        ));
        for release in releases {
            release.send(()).unwrap();
        }
        for job in jobs {
            let _ = job.await;
        }
        tokio::time::timeout(std::time::Duration::from_secs(5), async {
            while SLOTS.available_permits() != 2 {
                tokio::task::yield_now().await;
            }
        })
        .await
        .unwrap();
        assert!(run(|| Ok(())).await.is_ok());
    }
}
