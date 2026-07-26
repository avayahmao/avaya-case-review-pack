# SIP / Voice Quality / Codec Troubleshooting Reference

Reference for Avaya Aura SIP signaling, RTP/voice quality, codec negotiation,
Session Manager trace, SIP trunk registration, SBC, and QoS troubleshooting.

## Table of Contents
- [SIP Signaling Analysis (Workflow 3)](#sip-signaling-analysis)
- [Voice Quality (Workflow 6)](#voice-quality)
- [SIP Trunk Registration (Workflow 19)](#sip-trunk-registration)
- [Voice Quality QoS (Workflow 20)](#voice-quality-qos)
- [Codec Mismatch (Workflow 22)](#codec-mismatch)
- [Outbound Call Failures (Workflow 27)](#outbound-call-failures)
- [CM Error Diagnosis (Workflow 21)](#cm-error-diagnosis)
- [Session Manager Trace (§3.3)](#session-manager-trace)
- [CM ↔ SM Integration (§5.3)](#cm--sm-integration)
- [SIP / Voice Fault Patterns](#sip--voice-fault-patterns)
- [Historical SIP / Voice Fault Patterns](#historical-sip--voice-fault-patterns)

---

## SIP Signaling Analysis

**Workflow 3: SIP Signaling Analysis**

```
Step 1 — Identify SIP Path
  Client → SM → CM (direct SIP station)
  Client → SM → SM → CM (multi-domain)
  External → SBC → SM → CM (inbound)

Step 2 — Collect SIP Traces
  SM:  satrace -c capture -s <duration> or System Manager > SIP Trace
  CM:  list trace signaling-group <n> or traceSM (if applicable)
  SBC: capture per vendor documentation

Step 3 — Analyze SIP Message Flow
  For each INVITE/200 OK/ACK/BYE sequence:
    - Verify Request-URI, To, From headers
    - Check SDP offer/answer (codec negotiation, media address)
    - Look for: 408/480/486/503 errors
    - Track: P-Asserted-Identity, P-Charge-Info, Diversion headers

Step 4 — Identify Common SIP Issues
  - One-way audio: SDP media address mismatch, NAT traversal
  - Registration failure: 403/401, certificate issues, DNS resolution
  - Call setup failure: 486 Busy, 480 Temporarily Unavailable, 408 Timeout
  - DTMF issues: RFC2833 vs SIP INFO vs KPML mismatch
  - Display/CLI issues: PAI/RPID header manipulation at each hop
```

---

## Voice Quality

**Workflow 6: Voice Quality Troubleshooting**

```
Step 1 — Characterize the Problem
  - One-way audio / Two-way audio / Choppy / Echo / Delay / No audio
  - Internal calls only / External calls only / Specific trunks

Step 2 — Collect Data
  - CM: list measurement ip-network-region <n>
  - CM: list measurement dsp-resource
  - SM: satrace RTP statistics
  - Network: ping, traceroute between endpoints (port 5004/5006 for RTP)
  - Endpoint: codec in use (G.711/G.729/G.722), packetization time

Step 3 — Analyze
  - One-way audio: routing, firewall, NAT, IP-Network-Region mapping
  - Choppy: packet loss, jitter, insufficient DSP, CPU oversubscription
  - Echo: impedance mismatch, echo cancellation settings
  - Delay: codec selection (G.729 adds latency), network path, CM processing

Step 4 — Common Fixes
  - IP-Network-Region: correct codec set, direct-media, QoS mapping
  - Firewall: open RTP port range bidirectionally
  - DSP shortage: add resources, adjust codec preference
  - Codec mismatch: align endpoint ↔ CM ↔ trunk codec capabilities
```

---

## SIP Trunk Registration

**Workflow 19: SIP Trunk Registration Failure Diagnosis**

```
When a SIP trunk fails to register with a third-party service provider:

Step 1 — Initial Verification
  - Verify physical/network connectivity: ping provider gateway from SBC/SM
  - Check network settings (IP, subnet, gateway, DNS) on SBC and Session Manager
  - Verify SIP trunk license is available and assigned

Step 2 — Capture SIP Registration Exchange
  On Avaya SBC (SSH port 222 with root):
    traceSBC -i <provider_IP> -r "REGISTER"
    Use 'w' command to write output to pcap for Wireshark analysis
  On Session Manager:
    traceSM → filter by IP or URI → observe REGISTER/200 OK/401 flow

Step 3 — Interpret SIP Response Codes
  | Code | Meaning | Action |
  |------|---------|--------|
  | 401 Unauthorized | Provider challenging credentials | Verify auth username/password in SM SIP Entity config |
  | 403 Forbidden | Source IP not allowed or wrong credentials | Check provider ACL; verify IP whitelisting |
  | 408 Request Timeout | Network unreachable or firewall blocking | Check firewall rules for SIP port (5060/5061) |
  | 404 Not Found | SIP domain or user misconfigured | Verify Request-URI and SIP domain in trunk settings |
  | 405 Method Not Allowed | REGISTER not permitted for this URI | Check provider configuration for registration method |
  | 200 OK | Registration successful | Validate trunk status in SMGR and SBC dashboards |

Step 4 — Resolve Authentication Issues
  - Verify credentials in SM SIP Entity match provider records
  - Check authentication method (Digest MD5 vs other)
  - Examine WWW-Authenticate header in 401 response for required scheme

Step 5 — Validate After Fix
  - Confirm 200 OK received for REGISTER
  - Check registration status in SMGR → Elements → Session Manager → Entities
  - Place test call inbound and outbound
  - Monitor for registration refresh intervals (default 3600s)
```

> Note: IP Office SSA-based SIP trunk diagnostics are covered in `ip-office.md`.

---

## Voice Quality QoS

**Workflow 20: Voice Quality / QoS Diagnosis**

```
When users report choppy audio, echo, missing words, or one-way audio:

Step 1 — Isolate Scope
  - Internal calls only? → LAN/QoS issue
  - External calls only? → WAN/trunk/provider issue
  - Remote workers only? → VPN/bandwidth issue
  - Specific site? → Network segment issue

Step 2 — Phone-Based Diagnostics (Quick Check)
  Many Avaya IP phones have built-in network statistics:
  - Access phone web UI → Statistics or QoS page
  - Check real-time jitter, latency, packet loss for active call
  - This is the fastest way to confirm a network performance issue

Step 3 — Network Monitoring Tools
  | Tool | Metric | Notes |
  |------|--------|-------|
  | Wireshark RTP Stream Analysis | Jitter, packet loss, delta time | Capture via SPAN/mirror port; Telephony > RTP > Stream Analysis |
  | SolarWinds VNQM | MOS, jitter, latency, CDR analysis | Analyzes Avaya CM CDRs for proactive monitoring |
  | PRTG QoS Sensor | Jitter, packet loss between two points | QoS Round Trip Sensor or Ping Jitter Sensor |
  | CM list measurement | DSP resource usage, IP-NR metrics | Per-region performance data |

Step 4 — Key Metric Thresholds
  | Metric | Acceptable | Degraded | Unacceptable |
  |--------|-----------|----------|--------------|
  | One-way latency | < 150ms | 150-300ms | > 300ms |
  | Jitter | < 30ms | 30-50ms | > 50ms |
  | Packet loss | < 0.5% | 0.5-1% | > 1% |
  | MOS | > 4.0 | 3.5-4.0 | < 3.5 |

Step 5 — End-to-End QoS Verification
  Check EVERY hop in the call path:
  a) VLAN: Voice traffic on dedicated voice VLAN (separate from data)
  b) DSCP Marking: Voice packets (SIP signaling + RTP media) marked with correct DSCP/CoS
     - Typically DSCP EF (46) for RTP, CS3 (24) for SIP signaling
     - Verify marking at the phone (endpoint) level
  c) Switch/Router Policies: Network devices must trust and prioritize marked packets
     - Verify trust boundary configuration on access switches
     - Check queuing policies on distribution/core switches
  d) WAN Links: Provider must honor QoS markings; verify sufficient bandwidth provisioned

Step 6 — Codec Optimization
  - G.711: Best quality, highest bandwidth (64 kbps + overhead)
  - G.729: Lower bandwidth (8 kbps), adds ~25ms latency for compression
  - G.722: HD voice, 64 kbps, better quality than G.711
  - Ensure consistent codec set across IP-Network-Regions to avoid transcoding
  - Check CM: display ip-codec-set <n> and display ip-network-region <n>
```

---

## Codec Mismatch

**Workflow 22: Codec Mismatch Troubleshooting**

```
When calls fail with no audio, one-way audio, or 488 Not Acceptable Here:

Step 1 — Capture SIP/SDP for the Failed Call
  traceSM on Session Manager:
    - Filter by extension or IP
    - Find INVITE → examine SDP m=audio line for offered codecs (rtpmap entries)
    - Find 200 OK → examine SDP for accepted codec
    - If 488 Not Acceptable Here returned → codec mismatch confirmed

  Wireshark (alternative):
    - Capture from SPAN/mirror port
    - Filter: sip
    - Inspect INVITE and 200 OK SDP bodies

Step 2 — Identify the Mismatch
  - INVITE offers: G.711MU (payload 0), G.729 (payload 18)
  - 200 OK returns: G.711A (payload 8) only
  - No common codec → 488 error or silent call
  - Also check c= line for incorrect/unreachable IP address (NAT issue)

Step 3 — Resolve in Communication Manager
  CM SAT commands:
    display ip-network-region <region> → note Codec Set number
    change ip-codec-set <set_number> → add missing codec to both regions
    Ensure common codec (G.711MU, G.711A, or G.729) exists in ALL codec sets
    Check SRTP settings: media encryption must match endpoint capabilities
      (e.g., 1-srtp-aescm128-hmac80)

Step 4 — Resolve on SBC
  - Check media profiles / coder groups for both legs
  - Ensure at least one common codec on enterprise-side and carrier-side
  - Enable transcoding if endpoints cannot share a codec (requires SBC license)
  - Verify Media Security Mode and NAT Traversal settings in IP profiles
```

---

## Outbound Call Failures

**Workflow 27: Outbound Call Failures on SIP Trunk**

```
When SIP trunk is registered but outbound calls fail:

Step 1 — Confirm Trunk Status
  status trunk-group <N> → verify in-service, members available

Step 2 — Capture Full SIP Call Flow
  traceSM on Session Manager:
    - Capture INVITE from CM → SM → SBC → provider
    - Follow call to see where it fails and what response code returns

Step 3 — Interpret SIP Failure Codes
  | Code | Meaning | Action |
  |------|---------|--------|
  | 403 Forbidden | Calling number not authorized or format wrong | Check CPN format in route pattern |
  | 503 Service Unavailable | Provider overloaded or SBC routing issue | Check provider status; verify SBC routing |
  | 404 Not Found | Dialed number invalid at provider | Check number format (missing country code?) |
  | 480 Temporarily Unavailable | Called party unavailable | Destination issue |
  | 486 Busy Here | Called party busy | Destination issue |
  | 488 Not Acceptable Here | Codec mismatch | Check codec set on trunk group |
  | 608 Rejected | SBC or carrier rejecting call | Check carrier config and trunk capacity |

Step 4 — SBC Diagnostics
  - Access SBC management interface → active sessions and call logs
  - Use SBC packet capture to see full SIP ladder and SDP
  - Check SBC header manipulation rules (may be altering critical headers)
  - Verify SBC codec transcoding configuration
```

---

## CM Error Diagnosis

**Workflow 21: CM System-Level Error Diagnosis (display errors)**

```
Step 2 — Key Error Types:
  | 257 | PN Reset Level 2 | Check PN communication links |
  | 513 | PN Out of Service | Investigate PKT-INTF/EXP-INTF |
  | 769 | PN Emergency | Hardware inspection; escalate |
  | 542 | Translation Save Failure | Manually save translations |
  | 1025 | Station/TN Error | Check physical connectivity |
  | 1281 | Trunk Error | status trunk-group; test trunk |

Step 3 — Key Source Codes:
  | PKT-INT | IP Server Interface | IPSI sanity check failure |
  | LIC-ERR | License Error | License expired; test license |
  | DS1-BD | DS1 Board Error | PRI/T1 physical layer |
  | PRA-TRK | PRI Trunk Error | D-channel or B-channel fault |

Step 4 — Correlate with: display alarms, status media-gateway, list history
```

---

## Session Manager Trace

**§3.3 Session Manager Trace**

```bash
# SIP trace via CLI
satrace -c capture -s 300    # capture for 300 seconds

# Via System Manager
# Elements → Session Manager → Troubleshooting → SIP Trace
# Select SM, start trace, reproduce, stop, download

# Log locations on SM
/var/log/avaya/smsnapin/
```

---

## CM ↔ SM Integration

**§5.3 CM ↔ SM**

```
Protocol:    SIP (UDP/TCP/TLS)

Data Flow:
  Endpoint → SM (SIP Register, INVITE)
  SM → CM (SIP INVITE via SIP trunk / signaling group)

Key Fields:
  Request-URI, To, From, P-Asserted-Identity
  SDP: codec, media address, packetization

Common Issues:
  - Registration failure: DNS, certificates, domain configuration
  - Audio issues: IP-Network-Region, codec mismatch, NAT
  - Routing failure: dial pattern, route policy, CM trunk selection
```

---

## SIP / Voice Fault Patterns

**§4.2 SIP Signaling Patterns**

| Pattern | Symptoms | Root Cause | Resolution |
|---------|----------|------------|------------|
| **One-way audio after transfer** | Caller hears agent, agent doesn't hear caller | SDP re-INVITE fails, media anchored at wrong point | Check IP-Network-Region direct-media setting |
| **Registration flood** | Phones repeatedly register/deregister | DNS timeout, certificate mismatch, network congestion | Fix DNS/cert, check NTP, reduce registration interval |
| **Caller ID stripping** | External number shows as internal | PAI header overwritten at SIP hop (SM or SBC) | Preserve PAI through SIP profiles, check trust configuration |

---

## Historical SIP / Voice Fault Patterns

Patterns scoped to SIP signaling, RTP/media, codec, SM/SBC, QoS, voice quality,
and SIP-trunk registration. Sourced from FY21–FY23 SR cases (§4.10–4.13 of the
master agent file).

| Pattern | Symptoms | Root Cause | Resolution |
|---------|----------|------------|------------|
| **DMCC StationLink unregistration (Telecommuter)** | Unexpected DMCC device unregister when using StationLink Telecommuter mode | StationLink keepalive timeout or SIP re-INVITE failure for remote workers | Check network stability for remote agents; increase keepalive interval (per `1-1791095361`) |
| **ACR design difference causing ACRA behave differently** | Same recording config, different behavior across sites | CM design parameters (region, trunk, DSP) affect recording capture | Compare CM design parameters between sites; check IP-network-region and trunk group settings (per `1-18106641046`) |
| **ACCS voice quality issue after upgrade** | Voice quality degraded after IPO and ACCS upgrade | Codec or DSP configuration changed during upgrade | Verify codec settings post-upgrade; check DSP resources and IP-network-region (per `1-19480241832`) |
| **SIP INFO DTMF not recognized** | IVR does not respond to DTMF from SIP phones using SIP INFO | DTMF method mismatch (SIP INFO vs RFC2833) between phone and AEP | Configure matching DTMF method on phone and AEP (per `1-18702096522`) |
| **WebRTC one-way video** | WebRTC call has voice but video only in one direction | SDP video negotiation or firewall RTP port issue | Check SDP video offer/answer; verify firewall allows RTP video ports bidirectionally (per `1-17332616732`, `1-17390788680`) |
