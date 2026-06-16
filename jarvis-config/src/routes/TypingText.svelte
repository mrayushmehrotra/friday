<script lang="ts">
    let {text}: {text: string} = $props();
    let displayed = $state('');

    $effect(() => {
        displayed = '';
        let i = 0;
        const interval = setInterval(() => {
            if (i < text.length) {
                displayed += text[i];
                i++;
            } else {
                clearInterval(interval);
            }
        }, 15 + Math.random() * 20);
        return () => clearInterval(interval);
    });
</script>

{displayed}
