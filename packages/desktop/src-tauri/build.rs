fn main() {
    // The dev-mode sidecar lives at binaries/tempest-server-<triple>; expose the triple so
    // runtime path resolution matches what build-server.sh staged.
    println!(
        "cargo:rustc-env=TEMPEST_TARGET_TRIPLE={}",
        std::env::var("TARGET").expect("cargo always sets TARGET")
    );
    tauri_build::build()
}
