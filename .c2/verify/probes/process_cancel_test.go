// Copy into a scratch c2j pkg/ops/process checkout for native cancellation.
package process

import (
 "context"
 "errors"
 "os"
 "path/filepath"
 "testing"
 "time"

 "github.com/colony-2/c2j/internal/celltest"
 "github.com/stretchr/testify/require"
)

func TestRootCommandCancellationTerminatesDescendants(t *testing.T) {
 root := t.TempDir()
 ctx, cancel := context.WithCancel(celltest.Context(context.Background()))
 defer cancel()
 ready := filepath.Join(root, "ready")
 go func() {
  for i := 0; i < 200; i++ {
   if _, err := os.Stat(ready); err == nil { cancel(); return }
   time.Sleep(10*time.Millisecond)
  }
  cancel()
 }()
 started := time.Now()
 _, _, err := ExecuteProcess(ctx, RunRequest{WorkingDir: root, Shell: "sh",
  Run: "echo available-evidence > evidence.log; (sleep 1; echo leaked > survived) & touch ready; sleep 60"})
 require.True(t, errors.Is(err, context.Canceled), "expected typed cancellation, got %v", err)
 require.Less(t, time.Since(started), 3*time.Second)
 time.Sleep(1200*time.Millisecond)
 _, statErr := os.Stat(filepath.Join(root, "survived"))
 require.True(t, os.IsNotExist(statErr), "owned descendant survived cancellation")
 evidence, err := os.ReadFile(filepath.Join(root, "evidence.log"))
 require.NoError(t, err)
 require.Equal(t, "available-evidence\n", string(evidence))
}
