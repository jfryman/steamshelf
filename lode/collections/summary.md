# Collections

What a Steam collection actually is, and the rules governing which ones
steamshelf may touch.

```mermaid
flowchart TB
    NS["cloud namespace 1"] --> E["entries"]
    E --> UC["user-collections.* (~62)"]
    E --> OTHER["GameReleased, NewContentRollup_*, ... (~114)"]
    UC --> STATIC["static: added[] / removed[]"]
    UC --> DYN["dynamic: filterSpec"]
    UC --> BUILT["built-in: favorite, hidden"]
    UC --> TOMB["tombstones: is_deleted"]
    STATIC --> W{"writable?"}
    W -->|"can_produce()"| YES["steamshelf may write"]
    W -->|"otherwise"| NO["read only"]
```

Only static, non-built-in, non-deleted collections are even candidates, and of
those only the ones this config could itself have created are writable. That
second rule is the important one and is explained in
[naming-and-ownership.md](naming-and-ownership.md).

## Files

| File | Contents |
|---|---|
| [collection-model.md](collection-model.md) | The JSON shape and its parsing |
| [naming-and-ownership.md](naming-and-ownership.md) | Depressurizer compatibility; owns vs can_produce |
| [local-mirror.md](local-mirror.md) | Reading collections without logging in |

Related: [../cm/cloudconfigstore.md](../cm/cloudconfigstore.md),
[../pipeline/summary.md](../pipeline/summary.md)
