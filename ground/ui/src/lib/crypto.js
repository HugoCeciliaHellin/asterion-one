/**
 * Asterion One — Client-Side Ed25519 Cryptography
 * =================================================
 * Reference: Art.7 SD-1A steps 2-4 (Sign on client)
 * Reference: Art.8 §2.3 IF-WS-002 (Canonical JSON specification)
 *
 * SECURITY DESIGN:
 *   - Private key NEVER leaves the browser [Art.4 F1.2]
 *   - Ground API only stores/retransmits the signature
 *   - Uses tweetnacl library (standard Ed25519, RFC 8032)
 *
 * Implementation: Phase 3
 */

// import nacl from 'tweetnacl';
// import naclUtil from 'tweetnacl-util';

/**
 * Sign a command plan using Ed25519.
 *
 * Steps (Art.7 SD-1C):
 *   1. Compute canonical JSON of commands (sorted keys)
 *   2. Compute SHA-256 hash of canonical JSON
 *   3. Sign hash with Ed25519 private key
 *
 * @param {Array} commands - Array of command objects
 * @param {Uint8Array} privateKey - Ed25519 private key (64 bytes)
 * @returns {{ signature: string, publicKey: string }} Base64-encoded signature and public key
 */
export async function signPlan(commands, privateKey) {
  // Phase 3 implementation
  throw new Error('signPlan not yet implemented — Phase 3');
}

/**
 * Generate a new Ed25519 keypair for the operator.
 *
 * @returns {{ publicKey: Uint8Array, secretKey: Uint8Array }}
 */
export function generateKeypair() {
  // Phase 3 implementation
  throw new Error('generateKeypair not yet implemented — Phase 3');
}

/**
 * Compute canonical JSON string from commands array.
 * Both client (JS) and server (Python) MUST produce identical output.
 *
 * Reference: Art.8 §2.3 IF-WS-002 — Canonical JSON for signing
 *
 * @param {Array} commands - Array of command objects
 * @returns {string} Deterministic JSON string
 */
export function canonicalJSON(commands) {
  // Phase 3 implementation
  // return JSON.stringify(commands, Object.keys(commands[0]).sort());
  throw new Error('canonicalJSON not yet implemented — Phase 3');
}
