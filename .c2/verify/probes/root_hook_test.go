// Copy into a scratch c2j pkg/worker/compiler checkout to test the actual hook.
package compiler

import (
 "context"
 "encoding/json"
 "os"
 "testing"

 "github.com/colony-2/c2j/pkg/recipe"
 "github.com/colony-2/c2j/pkg/worker/commandop"
 "github.com/colony-2/jobdb/pkg/jobdb"
 "github.com/stretchr/testify/require"
)

func TestRootHookTypedCancellation(t *testing.T) {
 withRegisteredOps(t, commandop.GetOp())
 data, err := os.ReadFile(os.Getenv("ROOT_VERIFY_HOOK"))
 require.NoError(t, err)
 // ExecuteRecipe is a top-level entry point and validates raw inputs.
 // Late include compatibility is tested separately by the real caller. Add
 // only an adapter schema here, leaving the actual hook body unchanged.
 var adapter map[string]interface{}
 require.NoError(t, json.Unmarshal(data, &adapter))
 adapter["input_schema"] = map[string]interface{}{
  "api_version": map[string]interface{}{"type": "string"},
  "candidate": map[string]interface{}{"type": "string"},
  "base": map[string]interface{}{"type": "string"},
 }
 data, err = json.Marshal(adapter)
 require.NoError(t, err)
 r, err := recipe.LoadRecipeFromString(data)
 require.NoError(t, err)
 for stop, name := range []string{"catalog", "acceptance", "docs", "summarize"} {
  t.Run(name, func(t *testing.T) {
   jobCtx, gitCtx := GenerateTestContext()
   script := &catchScriptedJobContext{jobKey: jobdb.JobKey{TenantId: "tenant", JobId: "root-cancel"}}
   for i := 0; i < stop; i++ {
    script.results = append(script.results, catchTaskResult{out: catchOutput(t, gitCtx, map[string]interface{}{
     "success": true, "exit_code": 0, "timed_out": false, "stdout": "", "error_message": "",
    })})
   }
   script.results = append(script.results, catchTaskResult{err: context.Canceled})
   inputs := map[string]interface{}{"api_version": "c2.build-hook/v1", "candidate": "candidate", "base": "base"}
   out, _, runErr := ExecuteRecipe(catchWorkflowContext(script), *r, inputs, jobCtx, gitCtx)
   require.ErrorIs(t, runErr, context.Canceled)
   require.Empty(t, out, "cancellation must not return passed or a semantic failure")
   require.Equal(t, stop+1, script.calls, "no later operation may run after cancellation")
  })
 }
}
