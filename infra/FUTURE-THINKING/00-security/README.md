# Component: 00-Security (FUTURE USE ONLY)

**WARNING:** This component is a placeholder pattern for a future requirement to use Customer-Managed KMS Keys. It should NOT be deployed to any environment until that requirement is active.

### Activation Plan
To activate this component:
1. Move the `00-security` directory back into the parent `components/` directory.
2. Update the `02-stateful-resources` component to use a Customer-Managed Key, referencing the outputs of this component.
3. Add the necessary steps to the deployment pipeline to deploy `00-security` first.